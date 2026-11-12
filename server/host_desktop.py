"""Separate approval and credentials for Kali host desktop accounts."""
import os
import re
import subprocess
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import abort, g, jsonify, request

from rental_common import valid_id, validate_public_key


HOST_DESKTOP_SCHEMA = """
CREATE TABLE IF NOT EXISTS host_desktop_requests (
 user_id TEXT PRIMARY KEY REFERENCES users(id),
 linux_user TEXT NOT NULL UNIQUE,
 public_key TEXT NOT NULL,
 password_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','ready','revoked','failed')),
 requested_at INTEGER NOT NULL,
 updated_at INTEGER NOT NULL,
 approved_by TEXT REFERENCES users(id),
 approved_at INTEGER,
 applied_at INTEGER,
 last_error TEXT
);
CREATE INDEX IF NOT EXISTS host_desktop_status ON host_desktop_requests(status,requested_at);
"""


def hash_desktop_password(password):
    """Make a salted shadow-compatible hash without putting a password in argv."""
    try:
        result = subprocess.run(['/usr/bin/openssl', 'passwd', '-6', '-stdin'],
                                input=password + '\n', text=True, encoding='utf-8',
                                capture_output=True, timeout=8, check=True)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('원격 데스크톱 비밀번호를 준비하지 못했습니다.') from None
    hashed = result.stdout.strip()
    if not hashed.startswith('$6$') or len(hashed) > 300 or '\n' in hashed:
        raise RuntimeError('원격 데스크톱 비밀번호를 준비하지 못했습니다.')
    return hashed


def linux_username(user_id):
    if not valid_id(user_id):
        raise ValueError('Invalid member ID')
    return 'hbdesk_' + user_id[:16]


def capacity(app):
    try:
        configured = int(app.config.get('HOST_DESKTOP_MAX_USERS', 2))
    except (TypeError, ValueError):
        configured = 2
    return max(1, min(5, configured))


def register_host_desktop(app, db, fail, payload, require_verified_user, rate_limit, admins):
    def now():
        return int(time.time())

    def admin():
        require_verified_user()
        if g.user['id'] not in admins:
            abort(403)

    def public_row(row):
        if row is None:
            return None
        return {'status': row['status'], 'linuxUser': row['linux_user'] if row['status'] == 'ready' else None,
                'requestedAt': row['requested_at'], 'updatedAt': row['updated_at'],
                'approvedAt': row['approved_at'], 'appliedAt': row['applied_at'],
                'lastError': row['last_error'] if row['status'] == 'failed' else None}

    def audit(action, target):
        db().execute('INSERT INTO admin_events(actor_id,action,target,created_at) VALUES(?,?,?,?)',
                     (g.user['id'], 'host_desktop:' + action, target, now()))

    @app.get('/api/host-desktop')
    def get_host_desktop():
        require_verified_user()
        row = db().execute('SELECT * FROM host_desktop_requests WHERE user_id=?', (g.user['id'],)).fetchone()
        return jsonify(request=public_row(row), isAdmin=g.user['id'] in admins,
                       sshHost=app.config['HOST_DESKTOP_SSH_HOST'], sshPort=22,
                       remoteDesktopPort=3389, localDesktopPort=13389, capacity=capacity(app))

    @app.post('/api/host-desktop')
    def request_host_desktop():
        require_verified_user()
        if g.user['id'] in admins:
            return fail('관리자는 기존 Kali 계정으로 접속해 주세요.', 409)
        if not rate_limit('host-desktop-request', 5, 3600, g.user['id']):
            return fail('신청이 너무 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        data = payload()
        try:
            public_key = validate_public_key(data.get('publicKey'))
        except ValueError as error:
            return fail(str(error), 400)
        password = data.get('desktopPassword')
        if not isinstance(password, str) or not 12 <= len(password) <= 72 or not all(32 <= ord(char) <= 126 for char in password):
            return fail('원격 데스크톱 비밀번호는 영문 키보드에서 입력할 수 있는 12~72자로 정해 주세요.', 400)
        site_hash = db().execute('SELECT password_hash FROM users WHERE id=?', (g.user['id'],)).fetchone()['password_hash']
        if site_hash:
            try:
                if PasswordHasher().verify(site_hash, password):
                    return fail('사이트 로그인 비밀번호와 다른 비밀번호를 정해 주세요.', 400)
            except (InvalidHashError, VerificationError):
                pass
        try:
            password_hash = hash_desktop_password(password)
        except RuntimeError:
            return fail('원격 데스크톱 비밀번호를 준비하지 못했습니다.', 503)
        with db():
            db().execute('BEGIN IMMEDIATE')
            prior = db().execute('SELECT status FROM host_desktop_requests WHERE user_id=?', (g.user['id'],)).fetchone()
            if prior and prior['status'] in ('approved', 'ready'):
                return fail('이미 승인된 Kali 계정이 있습니다. 변경이 필요하면 관리자에게 문의해 주세요.', 409)
            username = linux_username(g.user['id'])
            timestamp = now()
            db().execute('''INSERT INTO host_desktop_requests
                (user_id,linux_user,public_key,password_hash,status,requested_at,updated_at)
                VALUES(?,?,?,?,'pending',?,?)
                ON CONFLICT(user_id) DO UPDATE SET public_key=excluded.public_key,
                password_hash=excluded.password_hash,status='pending',requested_at=excluded.requested_at,
                updated_at=excluded.updated_at,approved_by=NULL,approved_at=NULL,applied_at=NULL,last_error=NULL''',
                (g.user['id'], username, public_key, password_hash, timestamp, timestamp))
            audit('request', g.user['id'])
        return jsonify(request=public_row(db().execute('SELECT * FROM host_desktop_requests WHERE user_id=?',
                                                     (g.user['id'],)).fetchone())), 201

    @app.delete('/api/host-desktop')
    def cancel_host_desktop():
        require_verified_user()
        with db():
            row = db().execute('SELECT status FROM host_desktop_requests WHERE user_id=?', (g.user['id'],)).fetchone()
            if not row:
                abort(404)
            if row['status'] != 'revoked':
                db().execute("UPDATE host_desktop_requests SET status='revoked',updated_at=?,last_error=NULL WHERE user_id=?",
                             (now(), g.user['id']))
                audit('cancel', g.user['id'])
        return jsonify(ok=True)

    @app.get('/api/admin/host-desktops')
    def admin_host_desktops():
        admin()
        rows = db().execute('''SELECT r.*,u.display_name,u.email,u.email_verified_at,u.registration_completed_at
            FROM host_desktop_requests r JOIN users u ON u.id=r.user_id
            ORDER BY CASE r.status WHEN 'pending' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END,
                     r.updated_at DESC LIMIT 100''').fetchall()
        return jsonify(requests=[public_row(row) | {'userId': row['user_id'], 'name': row['display_name'],
                        'email': row['email'], 'verified': bool(row['email_verified_at'] and row['registration_completed_at'])}
                        for row in rows], capacity=capacity(app))

    @app.post('/api/admin/host-desktops/<user_id>/review')
    def review_host_desktop(user_id):
        admin()
        if not valid_id(user_id):
            abort(404)
        decision = payload().get('decision')
        if decision not in ('approve', 'revoke', 'retry'):
            return fail('승인, 재시도 또는 접속 해제를 선택해 주세요.', 400)
        with db():
            db().execute('BEGIN IMMEDIATE')
            row = db().execute('''SELECT r.status,u.email_verified_at,u.registration_completed_at
                FROM host_desktop_requests r JOIN users u ON u.id=r.user_id WHERE r.user_id=?''', (user_id,)).fetchone()
            if not row:
                abort(404)
            if decision in ('approve', 'retry'):
                expected = 'pending' if decision == 'approve' else 'failed'
                if row['status'] != expected:
                    return fail('현재 신청 상태에서는 이 작업을 할 수 없습니다.', 409)
                if not row['email_verified_at'] or not row['registration_completed_at']:
                    return fail('이메일 인증과 회원가입을 완료한 회원만 승인할 수 있습니다.', 409)
                count = db().execute("SELECT count(*) FROM host_desktop_requests WHERE status IN ('approved','ready')").fetchone()[0]
                if count >= capacity(app):
                    return fail('Kali 호스트 원격 접속 정원이 모두 사용 중입니다.', 409)
                db().execute('''UPDATE host_desktop_requests SET status='approved',updated_at=?,approved_by=?,
                    approved_at=?,last_error=NULL WHERE user_id=?''', (now(), g.user['id'], now(), user_id))
            else:
                if row['status'] == 'revoked':
                    return jsonify(ok=True)
                db().execute("UPDATE host_desktop_requests SET status='revoked',updated_at=?,last_error=NULL WHERE user_id=?",
                             (now(), user_id))
            audit(decision, user_id)
        return jsonify(ok=True)
