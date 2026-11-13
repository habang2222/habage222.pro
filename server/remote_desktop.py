"""Authenticated, same-origin browser gateway to the loopback-only RDP service.

The browser never selects a host, port, Linux username, or Guacamole connection
ID. Passwords exist only during the encrypted connection handshake, not in DBs,
URLs, command lines, or application logs.
"""
import codecs
import hashlib
import hmac
import json
import re
import secrets
import select
import socket
import time

from flask import abort, g, request
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from host_desktop import linux_username


REMOTE_SCHEMA = """
CREATE TABLE IF NOT EXISTS remote_connections (
 user_id TEXT PRIMARY KEY REFERENCES users(id),
 connection_id TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL
);
"""
LEASE_SECONDS = 20
MAX_CONNECTIONS = 4
ALLOWED_INPUT = {'sync', 'mouse', 'key', 'size', 'ack', 'nop', 'disconnect'}


def instruction(*values):
    return ','.join(f'{len(str(value))}.{value}' for value in values) + ';'


class Instructions:
    """Bounded incremental Guacamole parser; delimiters inside values are data."""
    def __init__(self, maximum=32768):
        self.buffer = ''
        self.maximum = maximum

    def feed(self, data):
        if not isinstance(data, str) or len(self.buffer) + len(data) > self.maximum:
            raise ValueError('Invalid protocol message')
        self.buffer += data
        complete = []
        while self.buffer:
            position = 0
            values = []
            while True:
                dot = self.buffer.find('.', position)
                if dot == -1:
                    if len(self.buffer) - position > 6:
                        raise ValueError('Invalid protocol length')
                    return complete
                prefix = self.buffer[position:dot]
                if not re.fullmatch(r'[0-9]{1,6}', prefix):
                    raise ValueError('Invalid protocol length')
                end = dot + 1 + int(prefix)
                if end > self.maximum:
                    raise ValueError('Protocol value too large')
                if len(self.buffer) <= end:
                    return complete
                values.append(self.buffer[dot + 1:end])
                if len(values) > 256:
                    raise ValueError('Too many protocol arguments')
                separator = self.buffer[end]
                if separator == ';':
                    complete.append(values)
                    self.buffer = self.buffer[end + 1:]
                    break
                if separator != ',':
                    raise ValueError('Invalid protocol separator')
                position = end + 1
        return complete


def browser_input(data, parser):
    messages = parser.feed(data)
    for values in messages:
        if not values or values[0] not in ALLOWED_INPUT or len(values) > 8:
            raise ValueError('Unsupported input instruction')
        opcode = values[0]
        if opcode in ('mouse', 'key', 'size', 'sync'):
            if not all(re.fullmatch(r'-?[0-9]{1,16}', value) for value in values[1:]):
                raise ValueError('Invalid input event')
        if opcode == 'key' and (len(values) != 3 or not 0 <= int(values[1]) <= 0xffffffff or values[2] not in ('0','1')):
            raise ValueError('Invalid keyboard event')
        if opcode == 'mouse' and (len(values) != 4 or not all(-32768 <= int(v) <= 32767 for v in values[1:3]) or not 0 <= int(values[3]) <= 31):
            raise ValueError('Invalid mouse event')
        if opcode == 'size' and (len(values) != 3 or not all(320 <= int(v) <= 2560 for v in values[1:])):
            raise ValueError('Invalid desktop size')
        if opcode == 'sync' and (len(values) != 2 or not 0 <= int(values[1]) < 2**53):
            raise ValueError('Invalid sync event')
        if opcode == 'ack' and (len(values) != 4 or not re.fullmatch(r'[0-9]{1,8}',values[1]) or
                                len(values[2]) > 128 or not re.fullmatch(r'[0-9]{1,5}',values[3])):
            raise ValueError('Invalid stream acknowledgement')
        if opcode in ('nop','disconnect') and len(values) != 1:
            raise ValueError('Invalid control event')
    return messages


def authorized_user(connection, user_id, session_hash, admins, now=None):
    """Recheck the live session and approval; no cached authorization decisions."""
    timestamp = int(time.time()) if now is None else now
    row = connection.execute('''SELECT u.id FROM users u JOIN sessions s ON s.user_id=u.id
        WHERE u.id=? AND s.token_hash=? AND s.expires_at>? AND u.email_verified_at IS NOT NULL
        AND u.registration_completed_at IS NOT NULL''', (user_id, session_hash, timestamp)).fetchone()
    if not row:
        return None
    if user_id in admins:
        return 'habang222'
    row = connection.execute("SELECT linux_user FROM host_desktop_requests WHERE user_id=? AND status='ready'",
                             (user_id,)).fetchone()
    if not row or row['linux_user'] != linux_username(user_id):
        return None
    return row['linux_user']


def acquire_lease(connection, user_id, connection_id, now):
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('DELETE FROM remote_connections WHERE expires_at<=?', (now,))
        if connection.execute('SELECT 1 FROM remote_connections WHERE user_id=?', (user_id,)).fetchone():
            return False
        if connection.execute('SELECT count(*) FROM remote_connections').fetchone()[0] >= MAX_CONNECTIONS:
            return False
        connection.execute('INSERT INTO remote_connections VALUES(?,?,?)',
                           (user_id, connection_id, now + LEASE_SECONDS))
    return True


def rdp_handshake(stream, username, password, width, height):
    stream.sendall(instruction('select', 'rdp').encode())
    parser = Instructions()
    args = None
    while args is None:
        data = stream.recv(8192)
        if not data:
            raise OSError('Remote service unavailable')
        for message in parser.feed(data.decode('utf-8')):
            if message[0] != 'args':
                raise ValueError('Unexpected remote handshake')
            args = message[1:]
    parameters = {
        'hostname': '127.0.0.1', 'port': '3389', 'username': username,
        'password': password, 'security': 'tls', 'ignore-cert': 'true',
        'color-depth': '16', 'resize-method': 'display-update',
        'disable-audio': 'true', 'enable-drive': 'false', 'enable-printing': 'false',
        'enable-wallpaper': 'false', 'enable-theming': 'false',
        'enable-font-smoothing': 'false', 'enable-full-window-drag': 'false',
        'disable-copy': 'true', 'disable-paste': 'true', 'timezone': 'Asia/Seoul',
        'server-layout': 'en-us-qwerty',
    }
    values = ['VERSION_1_5_0' if name.startswith('VERSION_') else parameters.get(name, '') for name in args]
    stream.sendall((instruction('size', width, height, 96) + instruction('audio') +
                    instruction('video') + instruction('image', 'image/png', 'image/jpeg') +
                    instruction('connect', *values)).encode('utf-8'))


def register_remote_desktop(app, db, csrf_token, require_verified_user, rate_limit, admins):
    app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 20, 'max_message_size': 32768,
                                         'subprotocols': ['guacamole']}
    sock = Sock(app)

    @app.before_request
    def protect_remote_handshake():
        if request.path != '/api/remote/host':
            return
        require_verified_user()
        if request.headers.get('Origin') != app.config['BASE_URL']:
            abort(403)

    @sock.route('/api/remote/host')
    def host_screen(ws):
        connection_id = secrets.token_hex(16)
        user_id = g.user['id']
        session_hash = hashlib.sha256(g.token.encode()).hexdigest()
        stream = None
        leased = False
        try:
            username = authorized_user(db(), user_id, session_hash, admins)
            if not username:
                ws.close(1008, '이메일 인증과 관리자 승인이 필요합니다.')
                return
            if not rate_limit('browser-desktop-connect', 12, 60, user_id):
                ws.close(1008, '접속 요청이 많습니다. 잠시 후 다시 시도해 주세요.')
                return
            raw = ws.receive(timeout=10)
            if not isinstance(raw, str) or len(raw) > 2048:
                raise ValueError('Missing connection information')
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) != {'csrfToken', 'password', 'width', 'height'}:
                raise ValueError('Invalid connection information')
            supplied = data.get('csrfToken')
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, csrf_token()):
                ws.close(1008, '로그인을 새로 확인해 주세요.')
                return
            password = data.get('password')
            if not isinstance(password, str) or not 1 <= len(password) <= 128 or any(ord(c) < 32 for c in password):
                raise ValueError('Invalid password input')
            width, height = data.get('width'), data.get('height')
            if type(width) is not int or type(height) is not int or not (640 <= width <= 1920 and 480 <= height <= 1200):
                raise ValueError('Invalid screen size')
            leased = acquire_lease(db(), user_id, connection_id, int(time.time()))
            if not leased:
                ws.close(1008, '이미 열린 원격 창을 닫거나 잠시 후 다시 접속해 주세요.')
                return
            stream = socket.create_connection(('127.0.0.1', 4822), timeout=10)
            rdp_handshake(stream, username, password, width, height)
            del raw, data, password
            stream.settimeout(5)
            with db():
                db().execute('INSERT INTO admin_events(actor_id,action,target,created_at) VALUES(?,?,?,?)',
                             (user_id, 'host_desktop:browser_connect', user_id, int(time.time())))
            parser = Instructions()
            decoder = codecs.getincrementaldecoder('utf-8')()
            started = last_input = checked = time.monotonic()
            input_window, input_bytes, input_count = started, 0, 0
            while True:
                now = time.monotonic()
                if now - started > 7200 or now - last_input > 1800:
                    ws.close(1000, '이용 시간이 끝났습니다. 다시 접속해 주세요.')
                    break
                if now - checked >= 2:
                    checked = now
                    if authorized_user(db(), user_id, session_hash, admins) != username:
                        ws.close(1008, '로그인 또는 접속 승인이 해제되었습니다.')
                        break
                    with db():
                        updated = db().execute('UPDATE remote_connections SET expires_at=? WHERE user_id=? AND connection_id=?',
                            (int(time.time()) + LEASE_SECONDS, user_id, connection_id)).rowcount
                    if not updated:
                        break
                incoming = ws.receive(timeout=0)
                if incoming is not None:
                    if now - input_window >= 1:
                        input_window, input_bytes, input_count = now, 0, 0
                    messages = browser_input(incoming, parser)
                    input_bytes += len(incoming)
                    input_count += len(messages)
                    if input_bytes > 262144 or input_count > 2000:
                        raise ValueError('Input rate exceeded')
                    for values in messages:
                        if values[0] in ('mouse', 'key'):
                            last_input = now
                        stream.sendall(instruction(*values).encode('utf-8'))
                if select.select([stream], [], [], 0.02)[0]:
                    incoming = stream.recv(65536)
                    if not incoming:
                        break
                    decoded = decoder.decode(incoming)
                    if decoded:
                        ws.send(decoded)
        except ConnectionClosed:
            pass
        except (ValueError, TypeError, OSError):
            # Never log handshake data, passwords, or low-level authentication errors.
            ws.close(1011, '원격 연결을 마치지 못했습니다. 비밀번호와 서버 상태를 확인해 주세요.')
        finally:
            if stream:
                stream.close()
            if leased:
                with db():
                    db().execute('DELETE FROM remote_connections WHERE user_id=? AND connection_id=?', (user_id, connection_id))
            try:
                ws.close()
            except ConnectionClosed:
                pass
