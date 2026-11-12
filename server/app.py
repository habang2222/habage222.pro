"""Same-origin membership and page comments for the existing static site."""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from contextlib import closing
from datetime import timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, Response, abort, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from portal import PORTAL_SCHEMA, register_portal
from host_desktop import HOST_DESKTOP_SCHEMA, register_host_desktop

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
SESSION_TTL = 60 * 60 * 24 * 7
ANON_SESSION_TTL = 30 * 60
PROOF_TTL = 10 * 60
EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT UNIQUE COLLATE NOCASE, password_hash TEXT,
 display_name TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS identities (
 provider TEXT NOT NULL, subject TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id),
 provider_email TEXT, PRIMARY KEY(provider, subject)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires_at INTEGER NOT NULL,
 created_at INTEGER
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
CREATE TABLE IF NOT EXISTS comments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, page TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id),
 body TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_page ON comments(page, id DESC);
CREATE TABLE IF NOT EXISTS rate_limits (
 bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS email_challenges (
 email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS privacy_requests (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK(kind IN ('export','delete')),
 message TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','acknowledged','completed','rejected')),
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS privacy_requests_owner ON privacy_requests(user_id, created_at DESC);
"""


def send_verification_email(config, recipient, code):
    """Send a short lived code; the code must never be logged or returned by the API."""
    message = EmailMessage()
    message['From'] = config['SMTP_FROM']
    message['To'] = recipient
    message['Subject'] = 'habang222 이메일 확인 코드'
    message.set_content(f'이메일 확인 코드는 {code}입니다. 10분 안에 입력해 주세요.\n요청하지 않았다면 무시하세요.')
    context = ssl.create_default_context()
    port = int(config['SMTP_PORT'])
    if config['SMTP_SECURITY'] == 'ssl':
        client = smtplib.SMTP_SSL(config['SMTP_HOST'], port, timeout=10, context=context)
    else:
        client = smtplib.SMTP(config['SMTP_HOST'], port, timeout=10)
    with client:
        if config['SMTP_SECURITY'] == 'starttls':
            client.starttls(context=context)
        if config['SMTP_USER']:
            client.login(config['SMTP_USER'], config['SMTP_PASSWORD'])
        client.send_message(message)


def create_app(config=None):
    load_dotenv(os.environ.get('ENV_FILE', Path(__file__).parent / '.env'))
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        BASE_URL=os.environ.get('BASE_URL', 'http://127.0.0.1:8080').rstrip('/'),
        DATABASE=os.environ.get('DATABASE', str(Path(__file__).parent / 'data/community.sqlite3')),
        SITE_ROOT=os.environ.get('SITE_ROOT', str(Path(__file__).resolve().parents[1])),
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=10),
        ADMIN_USER_IDS=os.environ.get('ADMIN_USER_IDS', ''),
        TRUST_PROXY=os.environ.get('TRUST_PROXY', '0') == '1',
        ALIAS_HOSTS=os.environ.get('ALIAS_HOSTS', ''),
        SMTP_HOST=os.environ.get('SMTP_HOST', ''),
        SMTP_PORT=os.environ.get('SMTP_PORT', '587'),
        SMTP_SECURITY=os.environ.get('SMTP_SECURITY', 'starttls'),
        SMTP_USER=os.environ.get('SMTP_USER', ''),
        SMTP_PASSWORD=os.environ.get('SMTP_PASSWORD', ''),
        SMTP_FROM=os.environ.get('SMTP_FROM', ''),
        HOST_DESKTOP_SSH_HOST=os.environ.get('HOST_DESKTOP_SSH_HOST', '100.110.205.65'),
        HOST_DESKTOP_MAX_USERS=os.environ.get('HOST_DESKTOP_MAX_USERS', '2'),
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('SECRET_KEY must be at least 32 characters')
    if app.config['SMTP_SECURITY'] not in ('starttls', 'ssl'):
        raise RuntimeError('SMTP_SECURITY must be starttls or ssl')
    try:
        smtp_port = int(app.config['SMTP_PORT'])
    except (TypeError, ValueError) as error:
        raise RuntimeError('SMTP_PORT must be a valid port') from error
    if not 1 <= smtp_port <= 65535:
        raise RuntimeError('SMTP_PORT must be a valid port')
    base = urlsplit(app.config['BASE_URL'])
    if base.scheme not in ('http', 'https') or not base.hostname or base.path or base.query or base.fragment:
        raise RuntimeError('BASE_URL must be an origin without a path')
    secure = base.scheme == 'https'
    cookie_name = '__Host-habang_sid' if secure else 'habang_sid'
    aliases = {v.strip().lower() for v in app.config['ALIAS_HOSTS'].split(',') if v.strip()} - {base.hostname}
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) for host in aliases):
        raise RuntimeError('ALIAS_HOSTS must contain hostnames without a scheme or path')
    app.config.update(
        SESSION_COOKIE_SECURE=secure,
        SESSION_COOKIE_NAME='__Host-habang_oauth' if secure else 'habang_oauth',
        TRUSTED_HOSTS=[base.hostname, 'localhost', '127.0.0.1', *aliases],
    )
    if app.config['TRUST_PROXY']:
        original = app.wsgi_app
        forwarded = ProxyFix(original, x_for=1)
        def local_proxy(environ, start_response):
            # Only the loopback reverse proxy can supply the visitor address.
            handler = forwarded if environ.get('REMOTE_ADDR') in ('127.0.0.1', '::1') else original
            return handler(environ, start_response)
        app.wsgi_app = local_proxy
    root = Path(app.config['SITE_ROOT']).resolve()
    pages = {'/' + p.name for p in root.glob('*.html')}
    admins = set(app.config['ADMIN_USER_IDS'].split(',')) - {''}
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
        conn.executescript(PORTAL_SCHEMA)
        conn.executescript(HOST_DESKTOP_SCHEMA)
        # Existing accounts retain their IDs and data, but must prove email
        # ownership and complete the new profile before privileged services.
        columns = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
        for column, definition in (
            ('full_name', 'TEXT'),
            ('email_verified_at', 'INTEGER'),
            ('registration_completed_at', 'INTEGER'),
        ):
            if column not in columns:
                conn.execute(f'ALTER TABLE users ADD COLUMN {column} {definition}')
        if 'created_at' not in {row[1] for row in conn.execute('PRAGMA table_info(sessions)')}:
            conn.execute('ALTER TABLE sessions ADD COLUMN created_at INTEGER')
        conn.execute('DELETE FROM sessions WHERE user_id IS NULL')
        conn.commit()

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        if 'db' in g:
            g.db.close()

    def fail(message, status=400):
        response = jsonify(error=message)
        response.status_code = status
        return response

    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def csrf_token():
        return hmac.new(app.config['SECRET_KEY'].encode(), g.token.encode(), hashlib.sha256).hexdigest()

    def anonymous_token():
        raw = f'a.{int(time.time())}.{secrets.token_urlsafe(18)}'
        signature = hmac.new(app.config['SECRET_KEY'].encode(), raw.encode(), hashlib.sha256).hexdigest()
        return f'{raw}.{signature}'

    def valid_anonymous_token(token):
        parts = token.split('.')
        if len(parts) != 4 or parts[0] != 'a':
            return False
        try:
            issued_at = int(parts[1])
        except ValueError:
            return False
        age = int(time.time()) - issued_at
        if age < -60 or age > ANON_SESSION_TTL:
            return False
        expected = hmac.new(app.config['SECRET_KEY'].encode(), '.'.join(parts[:3]).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(parts[3], expected)

    def new_session(user_id=None):
        if getattr(g, 'token', None) and not valid_anonymous_token(g.token):
            db().execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(g.token),))
        g.token = secrets.token_urlsafe(32) if user_id else anonymous_token()
        if user_id:
            db().execute('INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)',
                         (token_hash(g.token), user_id, int(time.time()) + SESSION_TTL, int(time.time())))
        if user_id or secrets.randbelow(100) == 0:
            db().execute('DELETE FROM sessions WHERE expires_at < ?', (int(time.time()),))
            db().execute('DELETE FROM rate_limits WHERE expires_at < ?', (int(time.time()),))
            db().execute('DELETE FROM email_challenges WHERE expires_at < ?', (int(time.time()),))
        db().commit()
        g.cookie_changed = True
        g.authenticated_at = int(time.time()) if user_id else None
        g.user = db().execute('SELECT id, email, display_name, full_name, email_verified_at, registration_completed_at FROM users WHERE id=?', (user_id,)).fetchone() if user_id else None

    @app.before_request
    def prepare_session():
        if request.host.partition(':')[0].lower() in aliases:
            if request.method in ('GET', 'HEAD'):
                return redirect(app.config['BASE_URL'] + request.full_path.removesuffix('?'), code=308)
            return fail('기본 사이트 주소에서 다시 시도해 주세요.', 403)
        g.user = None
        g.authenticated_at = None
        g.token = request.cookies.get(cookie_name, '')
        g.cookie_changed = False
        if not request.path.startswith(('/api/', '/auth/', '/downloads/')):
            return
        is_anonymous = valid_anonymous_token(g.token) if g.token else False
        stored = db().execute('SELECT user_id,created_at FROM sessions WHERE token_hash=? AND expires_at>? AND user_id IS NOT NULL',
                              (token_hash(g.token), int(time.time()))).fetchone() if g.token and not is_anonymous else None
        if stored:
            g.user = db().execute('SELECT id, email, display_name, full_name, email_verified_at, registration_completed_at FROM users WHERE id=?', (stored['user_id'],)).fetchone()
            g.authenticated_at = stored['created_at']
        elif is_anonymous:
            pass
        elif request.path == '/api/session' or request.path.startswith('/auth/'):
            if not rate_limit('anonymous-session', 300, 3600):
                return fail('요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
            new_session()
        else:
            g.token = ''
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('Origin') != app.config['BASE_URL']:
                return fail('요청 출처를 확인할 수 없습니다.', 403)
            supplied = request.headers.get('X-CSRF-Token', '')
            if not g.token or not hmac.compare_digest(supplied, csrf_token()):
                return fail('보안 정보가 만료되었습니다. 새로고침 후 다시 시도해 주세요.', 403)
            if not request.is_json:
                return fail('JSON 형식의 요청만 지원합니다.', 415)

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if request.path.startswith(('/api/', '/auth/', '/downloads/')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Cookie'
        elif request.path in ('/', '/index.html'):
            response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        elif request.path.endswith('.js'):
            # The homepage link list changes without renaming its script file.
            response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
        if getattr(g, 'cookie_changed', False):
            response.set_cookie(cookie_name, g.token, max_age=SESSION_TTL if g.user else ANON_SESSION_TTL, secure=secure,
                                httponly=True, samesite='Lax', path='/')
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return fail({400: '요청 내용을 확인해 주세요.', 404: '페이지를 찾을 수 없습니다.',
                     413: '입력 내용이 너무 큽니다.', 405: '지원하지 않는 요청입니다.'}.get(error.code, '요청을 처리할 수 없습니다.'), error.code)

    def payload():
        value = request.get_json()
        if not isinstance(value, dict):
            abort(400)
        return value

    def text(value):
        return value if isinstance(value, str) else ''

    def rate_limit(label, maximum, seconds, identity=None):
        now = int(time.time())
        key = hmac.new(app.config['SECRET_KEY'].encode(),
                       f'{label}:{identity or request.remote_addr}'.encode(), hashlib.sha256).hexdigest()
        bucket = f'{key}:{now // seconds}'
        with db():
            row = db().execute('''INSERT INTO rate_limits VALUES(?,1,?)
              ON CONFLICT(bucket) DO UPDATE SET count=count+1 RETURNING count''', (bucket, (now // seconds + 1) * seconds)).fetchone()
        return row['count'] <= maximum

    def public_user():
        return ({'id': g.user['id'], 'name': g.user['display_name'], 'email': g.user['email'],
                 'verified': bool(g.user['email_verified_at']),
                 'registrationComplete': bool(g.user['registration_completed_at']),
                 'isAdmin': g.user['id'] in admins} if g.user else None)

    def require_user():
        if not g.user:
            abort(401, description='로그인 후 이용해 주세요.')

    def require_verified_user():
        require_user()
        if not g.user['email_verified_at'] or not g.user['registration_completed_at']:
            abort(403, description='이메일 인증과 회원가입을 완료해 주세요.')

    def pending_registration():
        proof = session.get('pending_registration')
        if not isinstance(proof, dict) or int(time.time()) - proof.get('issued_at', 0) > PROOF_TTL:
            session.pop('pending_registration', None)
            return None
        if proof.get('provider') not in ('google', 'github', 'email') or not EMAIL.fullmatch(proof.get('email', '')):
            session.pop('pending_registration', None)
            return None
        return proof

    def pending_public():
        proof = pending_registration()
        return ({'email': proof['email'], 'provider': proof['provider'],
                 'suggestedName': proof.get('suggested_name', '')} if proof else None)

    def smtp_ready():
        return bool(app.config['SMTP_HOST'] and app.config['SMTP_FROM'] and
                    (not app.config['SMTP_USER'] or app.config['SMTP_PASSWORD']))

    def email_code_hash(email, code):
        return hmac.new(app.config['SECRET_KEY'].encode(), f'email:{email}:{code}'.encode(), hashlib.sha256).hexdigest()

    @app.get('/api/session')
    def current_session():
        return jsonify(user=public_user(), csrfToken=csrf_token(), pendingRegistration=pending_public(),
                       emailVerificationAvailable=smtp_ready(), providers={
            name: bool(oauth.create_client(name)) for name in ('google', 'github')
        })

    @app.get('/api/privacy-requests')
    def list_privacy_requests():
        require_user()
        rows = db().execute('SELECT id,kind,status,created_at,updated_at FROM privacy_requests '
                            'WHERE user_id=? ORDER BY created_at DESC LIMIT 25', (g.user['id'],)).fetchall()
        return jsonify(requests=[dict(row) for row in rows])

    @app.post('/api/privacy-requests')
    def create_privacy_request():
        require_user()
        data = payload()
        kind = data.get('kind')
        message = text(data.get('message')).strip()
        if kind not in ('export', 'delete') or len(message) > 1000 or any(ord(c) < 32 and c not in '\n\t' for c in message):
            return fail('요청 종류 또는 내용을 확인해 주세요.')
        if not rate_limit('privacy-request', 5, 86400, g.user['id']):
            return fail('요청 횟수를 초과했습니다. 지원 이메일로 문의해 주세요.', 429)
        now = int(time.time())
        with db():
            db().execute('BEGIN IMMEDIATE')
            duplicate = db().execute("SELECT 1 FROM privacy_requests WHERE user_id=? AND kind=? "
                                     "AND status IN ('pending','acknowledged')", (g.user['id'], kind)).fetchone()
            if duplicate:
                return fail('같은 종류의 요청을 이미 접수했습니다.', 409)
            row = (secrets.token_hex(16), g.user['id'], kind, message, 'pending', now, now)
            db().execute('INSERT INTO privacy_requests(id,user_id,kind,message,status,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?,?)', row)
        return jsonify(request={'id': row[0], 'kind': kind, 'status': 'pending',
                                'created_at': now, 'updated_at': now}), 201

    @app.get('/api/admin/privacy-requests')
    def admin_privacy_requests():
        require_user()
        if g.user['id'] not in admins:
            abort(403)
        rows = db().execute('''SELECT p.id,p.user_id,u.email,p.kind,p.message,p.status,p.created_at,p.updated_at
          FROM privacy_requests p JOIN users u ON u.id=p.user_id
          ORDER BY CASE WHEN p.status IN ('pending','acknowledged') THEN 0 ELSE 1 END,
                   p.created_at DESC LIMIT 100''').fetchall()
        return jsonify(requests=[dict(row) for row in rows])

    @app.post('/api/admin/privacy-requests/<request_id>/review')
    def review_privacy_request(request_id):
        require_user()
        if g.user['id'] not in admins:
            abort(403)
        status = payload().get('status')
        if status not in ('acknowledged', 'completed', 'rejected'):
            return fail('처리 상태를 확인해 주세요.')
        with db():
            row = db().execute('SELECT status FROM privacy_requests WHERE id=?', (request_id,)).fetchone()
            if not row:
                abort(404)
            if row['status'] in ('completed', 'rejected'):
                return fail('이미 완료된 요청입니다.', 409)
            if status == 'acknowledged' and row['status'] != 'pending':
                return fail('이미 접수 확인한 요청입니다.', 409)
            db().execute('UPDATE privacy_requests SET status=?,updated_at=? WHERE id=?',
                         (status, int(time.time()), request_id))
            db().execute('INSERT INTO admin_events(actor_id,action,target,created_at) VALUES(?,?,?,?)',
                         (g.user['id'], 'privacy:' + status, request_id, int(time.time())))
        return jsonify(ok=True)

    @app.post('/api/auth/link/<provider>')
    def begin_explicit_link(provider):
        require_user()
        if provider not in ('google', 'github'):
            abort(404)
        if not oauth.create_client(provider):
            return fail('이 인증 방식은 현재 준비 중입니다.', 503)
        if not g.user['email'] or not g.authenticated_at or int(time.time()) - g.authenticated_at > PROOF_TTL:
            return fail('계정 연결 전 비밀번호로 다시 로그인해 주세요.', 403)
        if not rate_limit('identity-link', 10, 3600, g.user['id']):
            return fail('계정 연결 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        next_page = text(payload().get('next'))
        next_page = next_page if next_page in pages or next_page == '/' else '/'
        session['link_user_id'] = g.user['id']
        session['link_issued_at'] = int(time.time())
        return jsonify(url=f'/auth/{provider}?' + urlencode({'next': next_page, 'link': '1'}))

    @app.post('/api/auth/email/start')
    def start_email_verification():
        if not smtp_ready():
            return fail('이메일 확인 메일 설정이 준비되지 않았습니다. Google 또는 GitHub로 인증해 주세요.', 503)
        email = text(payload().get('email')).strip().lower()
        if len(email) > 254 or not EMAIL.fullmatch(email):
            return fail('올바른 이메일 주소를 입력해 주세요.')
        if not rate_limit('email-start-ip', 5, 3600) or not rate_limit('email-start-address', 5, 3600, email):
            return fail('인증 메일 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        existing = db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        # Do not disclose whether another account already owns this address.
        if existing and (not g.user or existing['id'] != g.user['id']):
            return jsonify(sent=True), 202
        code = f'{secrets.randbelow(100_000_000):08d}'
        with db():
            db().execute('INSERT INTO email_challenges(email,code_hash,expires_at,attempts) VALUES(?,?,?,0) '
                         'ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at,attempts=0',
                         (email, email_code_hash(email, code), int(time.time()) + PROOF_TTL))
        try:
            send_verification_email(app.config, email, code)
        except (OSError, smtplib.SMTPException):
            with db():
                db().execute('DELETE FROM email_challenges WHERE email=? AND code_hash=?', (email, email_code_hash(email, code)))
            return fail('인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.', 503)
        return jsonify(sent=True), 202

    @app.post('/api/auth/email/verify')
    def verify_email_code():
        data = payload()
        email = text(data.get('email')).strip().lower()
        code = text(data.get('code')).strip()
        if len(email) > 254 or not EMAIL.fullmatch(email) or not re.fullmatch(r'\d{8}', code):
            return fail('이메일과 8자리 코드를 확인해 주세요.')
        if not rate_limit('email-check-ip', 20, 3600) or not rate_limit('email-check-address', 10, 3600, email):
            return fail('인증 시도가 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        with db():
            db().execute('BEGIN IMMEDIATE')
            challenge = db().execute('SELECT * FROM email_challenges WHERE email=?', (email,)).fetchone()
            if not challenge or challenge['expires_at'] < int(time.time()) or challenge['attempts'] >= 5:
                return fail('코드가 만료되었거나 올바르지 않습니다.', 400)
            if not hmac.compare_digest(challenge['code_hash'], email_code_hash(email, code)):
                db().execute('UPDATE email_challenges SET attempts=attempts+1 WHERE email=?', (email,))
                return fail('코드가 만료되었거나 올바르지 않습니다.', 400)
            db().execute('DELETE FROM email_challenges WHERE email=?', (email,))
        existing = db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if existing and (not g.user or existing['id'] != g.user['id']):
            return fail('이 이메일로 된 계정에 먼저 로그인해 주세요.', 409)
        session['pending_registration'] = {'provider': 'email', 'email': email,
                                           'user_id': existing['id'] if existing else None,
                                           'issued_at': int(time.time())}
        return jsonify(pendingRegistration=pending_public())

    @app.post('/api/auth/register')
    def register():
        if not rate_limit('signup', 10, 3600):
            return fail('가입 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        proof = pending_registration()
        if not proof:
            return fail('Google·GitHub 또는 이메일 코드로 먼저 신원을 확인해 주세요.', 403)
        data = payload()
        email = text(data.get('email')).strip().lower()
        name = text(data.get('name')).strip()
        full_name = text(data.get('fullName')).strip()
        password = text(data.get('password'))
        if email != proof['email']:
            return fail('인증한 이메일과 가입 아이디가 일치하지 않습니다.', 403)
        if not 2 <= len(name) <= 30 or any(ord(c) < 32 for c in name):
            return fail('닉네임은 2~30자로 입력해 주세요.')
        if not 2 <= len(full_name) <= 60 or any(ord(c) < 32 for c in full_name):
            return fail('이름은 2~60자로 입력해 주세요.')
        if not 12 <= len(password) <= 128:
            return fail('비밀번호는 12~128자로 입력해 주세요.')
        hashed = PASSWORDS.hash(password)
        user_id = proof.get('user_id') or secrets.token_hex(16)
        try:
            with db():
                db().execute('BEGIN IMMEDIATE')
                owner = db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
                if owner and owner['id'] != user_id:
                    return fail('이미 가입된 이메일입니다. 기존 계정으로 로그인한 뒤 인증해 주세요.', 409)
                if proof['provider'] in ('google', 'github'):
                    identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                                            (proof['provider'], proof['subject'])).fetchone()
                    if identity and identity['user_id'] != user_id:
                        return fail('이미 다른 계정에 연결된 소셜 계정입니다.', 409)
                if db().execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
                    # Keys issued before the newly verified account must not
                    # become usable merely because profile verification returns.
                    db().execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?',
                                 (int(time.time()), user_id))
                    db().execute('UPDATE users SET email=?,password_hash=?,display_name=?,full_name=?,email_verified_at=?,registration_completed_at=? WHERE id=?',
                                 (email, hashed, name, full_name, int(time.time()), int(time.time()), user_id))
                    db().execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
                else:
                    db().execute('INSERT INTO users(id,email,password_hash,display_name,created_at,full_name,email_verified_at,registration_completed_at) VALUES(?,?,?,?,?,?,?,?)',
                                 (user_id, email, hashed, name, int(time.time()), full_name, int(time.time()), int(time.time())))
                if proof['provider'] in ('google', 'github'):
                    db().execute('INSERT INTO identities(provider,subject,user_id,provider_email) VALUES(?,?,?,?) '
                                 'ON CONFLICT(provider,subject) DO UPDATE SET provider_email=excluded.provider_email',
                                 (proof['provider'], proof['subject'], user_id, email))
        except sqlite3.IntegrityError:
            return fail('이 이메일 또는 소셜 계정은 이미 사용 중입니다.', 409)
        session.clear()
        new_session(user_id)
        return jsonify(user=public_user(), csrfToken=csrf_token()), 201

    @app.post('/api/auth/login')
    def login():
        data = payload()
        email = text(data.get('email')).strip().lower()
        password = text(data.get('password'))
        if not rate_limit('login-ip', 40, 900) or not rate_limit('login-account', 10, 900, email[:254]):
            return fail('로그인 시도가 많습니다. 15분 후 다시 시도해 주세요.', 429)
        user = db().execute('SELECT id, password_hash FROM users WHERE email=?', (email,)).fetchone()
        try:
            valid = PASSWORDS.verify(user['password_hash'] if user else DUMMY_HASH, password) if len(password) <= 128 else False
        except (VerificationError, InvalidHashError):
            valid = False
        if not valid or not user:
            return fail('이메일 또는 비밀번호가 올바르지 않습니다.', 401)
        if PASSWORDS.check_needs_rehash(user['password_hash']):
            with db():
                db().execute('UPDATE users SET password_hash=? WHERE id=?', (PASSWORDS.hash(password), user['id']))
        new_session(user['id'])
        return jsonify(user=public_user(), csrfToken=csrf_token())

    @app.post('/api/auth/logout')
    def logout():
        session.clear()
        new_session()
        return jsonify(user=None, csrfToken=csrf_token())

    def page_key(raw):
        value = '/' if raw in ('/', '/index.html') else raw
        if value != '/' and value not in pages:
            abort(404)
        return value

    def comment_json(row):
        return {'id': row['id'], 'body': row['body'], 'author': row['display_name'],
                'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
                'canEdit': bool(g.user and row['user_id'] == g.user['id']),
                'canDelete': bool(g.user and (row['user_id'] == g.user['id'] or g.user['id'] in admins))}

    def comment_row(comment_id):
        row = db().execute('SELECT c.*, u.display_name FROM comments c JOIN users u ON u.id=c.user_id WHERE c.id=?', (comment_id,)).fetchone()
        if not row:
            abort(404)
        return row

    @app.get('/api/comments')
    def list_comments():
        page = page_key(request.args.get('page', '/'))
        before = request.args.get('before', type=int)
        if before is not None and before < 1:
            abort(400)
        rows = db().execute('''SELECT c.*,u.display_name FROM comments c JOIN users u ON c.user_id=u.id
          WHERE c.page=? AND (? IS NULL OR c.id<?) ORDER BY c.id DESC LIMIT 21''', (page, before, before)).fetchall()
        count = db().execute('SELECT count(*) FROM comments WHERE page=?', (page,)).fetchone()[0]
        return jsonify(comments=[comment_json(r) for r in rows[:20]], total=count,
                       nextBefore=rows[19]['id'] if len(rows) > 20 else None)

    def comment_body(data):
        body = text(data.get('body')).strip()
        if not 1 <= len(body) <= 2000 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', body):
            abort(400, description='댓글은 1~2,000자로 입력해 주세요.')
        return body

    @app.post('/api/comments')
    def create_comment():
        require_user()
        data = payload()
        page = page_key(text(data.get('page')))
        body = comment_body(data)
        if not rate_limit('comments', 10, 60, g.user['id']):
            return fail('댓글을 너무 빠르게 작성했습니다. 잠시 후 다시 시도해 주세요.', 429)
        now = int(time.time())
        with db():
            cur = db().execute('INSERT INTO comments(page,user_id,body,created_at,updated_at) VALUES(?,?,?,?,?)',
                               (page, g.user['id'], body, now, now))
        return jsonify(comment=comment_json(comment_row(cur.lastrowid))), 201

    @app.patch('/api/comments/<int:comment_id>')
    def edit_comment(comment_id):
        require_user()
        row = comment_row(comment_id)
        if row['user_id'] != g.user['id']:
            abort(403)
        body = comment_body(payload())
        if not rate_limit('comment-edits', 30, 60, g.user['id']):
            return fail('수정 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        with db():
            db().execute('UPDATE comments SET body=?,updated_at=? WHERE id=?', (body, int(time.time()), comment_id))
        return jsonify(comment=comment_json(comment_row(comment_id)))

    @app.delete('/api/comments/<int:comment_id>')
    def delete_comment(comment_id):
        require_user()
        row = comment_row(comment_id)
        if row['user_id'] != g.user['id'] and g.user['id'] not in admins:
            abort(403)
        with db():
            db().execute('DELETE FROM comments WHERE id=?', (comment_id,))
        return jsonify(ok=True)

    register_portal(app, db, fail, payload, text, require_verified_user, rate_limit, admins)
    register_host_desktop(app, db, fail, payload, require_verified_user, rate_limit, admins)

    oauth = OAuth(app)
    google_id = app.config.get('GOOGLE_CLIENT_ID', os.getenv('GOOGLE_CLIENT_ID'))
    google_secret = app.config.get('GOOGLE_CLIENT_SECRET', os.getenv('GOOGLE_CLIENT_SECRET'))
    github_id = app.config.get('GITHUB_CLIENT_ID', os.getenv('GITHUB_CLIENT_ID'))
    github_secret = app.config.get('GITHUB_CLIENT_SECRET', os.getenv('GITHUB_CLIENT_SECRET'))
    if google_id and google_secret:
        oauth.register('google', client_id=google_id, client_secret=google_secret,
                       server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                       client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'})
    if github_id and github_secret:
        oauth.register('github', client_id=github_id, client_secret=github_secret,
                       access_token_url='https://github.com/login/oauth/access_token',
                       authorize_url='https://github.com/login/oauth/authorize',
                       api_base_url='https://api.github.com/',
                       client_kwargs={'scope': 'read:user user:email', 'code_challenge_method': 'S256'})

    def move_legacy_identity(provider, subject, source_id, target_id, email):
        """Link only an empty legacy OAuth shell after both accounts are proven."""
        with db():
            db().execute('BEGIN IMMEDIATE')
            source = db().execute('SELECT email,password_hash,email_verified_at,registration_completed_at FROM users WHERE id=?',
                                  (source_id,)).fetchone()
            target = db().execute('SELECT email FROM users WHERE id=?', (target_id,)).fetchone()
            if (not source or not target or target['email'] != email or source['email'] or
                    source['password_hash'] or source['email_verified_at'] or source['registration_completed_at']):
                raise ValueError('Accounts require manual review')
            if db().execute('SELECT count(*) FROM identities WHERE user_id=?', (source_id,)).fetchone()[0] != 1:
                raise ValueError('Legacy identity has additional providers')
            for table in ('api_keys', 'rentals', 'rental_permissions'):
                if db().execute(f'SELECT 1 FROM {table} WHERE user_id=? LIMIT 1', (source_id,)).fetchone():
                    raise ValueError('Legacy identity has resources')
            identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                                    (provider, subject)).fetchone()
            if not identity or identity['user_id'] != source_id:
                raise ValueError('Identity changed during linking')
            db().execute('UPDATE comments SET user_id=? WHERE user_id=?', (target_id, source_id))
            db().execute('UPDATE identities SET user_id=?,provider_email=? WHERE provider=? AND subject=?',
                         (target_id, email, provider, subject))
            db().execute('DELETE FROM sessions WHERE user_id=?', (source_id,))
            # Keep the source user row for historic admin/download foreign keys.
            db().execute('INSERT INTO admin_events(actor_id,action,target,created_at) VALUES(?,?,?,?)',
                         (target_id, 'identity:explicit-link', source_id, int(time.time())))

    @app.get('/auth/<provider>')
    def oauth_begin(provider):
        if provider not in ('google', 'github'):
            abort(404)
        client = oauth.create_client(provider)
        if not client:
            return redirect('/?auth_error=unavailable')
        if not rate_limit('oauth', 30, 300):
            return fail('요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        if request.args.get('link') == '1':
            if (not g.user or session.get('link_user_id') != g.user['id'] or
                    int(time.time()) - session.get('link_issued_at', 0) > PROOF_TTL or
                    not g.authenticated_at or int(time.time()) - g.authenticated_at > PROOF_TTL):
                session.pop('link_user_id', None)
                session.pop('link_issued_at', None)
                return redirect('/?auth_error=reauth_required')
        else:
            session.pop('link_user_id', None)
            session.pop('link_issued_at', None)
        next_page = request.args.get('next', '/')
        session['next_page'] = next_page if next_page in pages or next_page == '/' else '/'
        return client.authorize_redirect(app.config['BASE_URL'] + f'/auth/{provider}/callback')

    @app.get('/auth/<provider>/callback')
    def oauth_callback(provider):
        if provider not in ('google', 'github'):
            abort(404)
        client = oauth.create_client(provider)
        if not client:
            return redirect('/?auth_error=unavailable')
        next_page = session.get('next_page', '/')
        try:
            token = client.authorize_access_token()
            if provider == 'google':
                # Authlib validates the ID token signature, issuer, audience and nonce.
                info = token.get('userinfo')
                if not info or not info.get('sub') or not info.get('email_verified'):
                    raise ValueError('Unverified identity')
                subject = str(info['sub'])
                name = info.get('name', 'Google 회원')
                email = info.get('email')
            else:
                response = client.get('user', token=token, timeout=10)
                response.raise_for_status()
                info = response.json()
                if not info.get('id'):
                    raise ValueError('Missing subject')
                subject = str(info['id'])
                name = info.get('name') or info.get('login') or 'GitHub 회원'
                emails = client.get('user/emails', token=token, timeout=10)
                emails.raise_for_status()
                email = next((e['email'] for e in emails.json() if e.get('verified') and e.get('primary')), None)
            email = text(email).strip().lower()
            if len(email) > 254 or not EMAIL.fullmatch(email):
                raise ValueError('Verified provider email is required')
            name = ''.join(c for c in str(name) if ord(c) >= 32).strip()[:30] or '회원'
            link_target = session.get('link_user_id')
            if link_target is not None and (
                    not g.user or g.user['id'] != link_target or g.user['email'] != email or
                    int(time.time()) - session.get('link_issued_at', 0) > PROOF_TTL or
                    not g.authenticated_at or int(time.time()) - g.authenticated_at > PROOF_TTL):
                session.clear()
                return redirect('/?auth_error=account_conflict')
            identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                                    (provider, subject)).fetchone()
            if link_target and identity and identity['user_id'] != link_target:
                try:
                    move_legacy_identity(provider, subject, identity['user_id'], link_target, email)
                except ValueError:
                    session.clear()
                    return redirect('/?auth_error=link_conflict')
                identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                                        (provider, subject)).fetchone()
            user_id = link_target or (identity['user_id'] if identity else None)
            owner = db().execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
            session.clear()
            if owner and owner['id'] != user_id:
                return redirect('/?auth_error=account_conflict')
            if link_target and not identity:
                with db():
                    db().execute('INSERT INTO identities(provider,subject,user_id,provider_email) VALUES(?,?,?,?)',
                                 (provider, subject, link_target, email))
                identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?',
                                        (provider, subject)).fetchone()
            if identity:
                account = db().execute('SELECT email,email_verified_at,registration_completed_at FROM users WHERE id=?',
                                       (user_id,)).fetchone()
                if account and account['email'] == email and account['email_verified_at'] and account['registration_completed_at']:
                    with db():
                        db().execute('UPDATE identities SET provider_email=? WHERE provider=? AND subject=?',
                                     (email, provider, subject))
                    new_session(user_id)
                    destination = next_page if next_page in pages or next_page == '/' else '/'
                    return redirect(destination + ('?auth_linked=' + provider if link_target else ''))
                if account and account['email'] != email:
                    with db():
                        db().execute('UPDATE users SET email_verified_at=NULL,registration_completed_at=NULL WHERE id=?', (user_id,))
                        db().execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE user_id=?', (int(time.time()), user_id))
                        db().execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            session['pending_registration'] = {'provider': provider, 'subject': subject,
                                               'email': email, 'suggested_name': name,
                                               'user_id': user_id, 'issued_at': int(time.time())}
            return redirect(next_page if next_page in pages or next_page == '/' else '/')
        except Exception:
            # Tokens and provider errors can contain secrets; do not print them.
            session.clear()
            return redirect('/?auth_error=failed')

    @app.get('/api/health')
    def health():
        db().execute('SELECT 1')
        return jsonify(ok=True)

    @app.get('/')
    @app.get('/<path:path>')
    def static_page(path='index.html'):
        parts = Path(path).parts
        if any(p.startswith('.') for p in parts) or '\\' in path:
            abort(404)
        allowed = ('/' + path in pages or (len(parts) == 1 and Path(path).suffix in ('.js', '.css'))
                   or (parts[0] == 'images' and Path(path).suffix.lower() in
                       ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico')))
        if not allowed:
            abort(404)
        if path == 'index.html':
            html = (root / path).read_text(encoding='utf-8')
            for filename in ('links.js', 'home.js'):
                digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()[:12]
                html = re.sub(rf'(?<=src="){re.escape(filename)}(?:\?v=[^"]*)?',
                              f'{filename}?v={digest}', html)
            return Response(html, mimetype='text/html')
        return send_from_directory(root, path)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=8080, debug=False)
