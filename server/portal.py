"""Member API keys, scoped read-only API, and approved container rentals."""
import hashlib
import json
import os
import secrets
import time
from functools import wraps
from pathlib import Path

from flask import abort, g, jsonify, request, send_file, send_from_directory, redirect
from rental_common import PLAN, RESERVED, TERMINAL, TRANSITIONS, capacity_limit, validate_public_key
from download_catalog import PROGRAMS, catalog, resolve_file

PORTAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token_hash TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL, scopes TEXT NOT NULL,
 created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, revoked_at INTEGER,
 last_used_at INTEGER, use_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS api_keys_owner ON api_keys(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS rental_permissions (
 user_id TEXT PRIMARY KEY REFERENCES users(id), approved INTEGER NOT NULL DEFAULT 0,
 updated_by TEXT NOT NULL REFERENCES users(id), updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rentals (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 plan TEXT NOT NULL, public_key TEXT NOT NULL, status TEXT NOT NULL,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, approved_by TEXT REFERENCES users(id),
 approved_at INTEGER, ssh_port INTEGER UNIQUE, expires_at INTEGER, last_error TEXT, ssh_fingerprint TEXT
);
CREATE INDEX IF NOT EXISTS rentals_owner ON rentals(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS rental_jobs (
 id TEXT PRIMARY KEY, rental_id TEXT NOT NULL REFERENCES rentals(id), action TEXT NOT NULL,
 status TEXT NOT NULL, created_at INTEGER NOT NULL, lease_until INTEGER, attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rental_jobs_queue ON rental_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS rental_runtime (
 id INTEGER PRIMARY KEY CHECK(id=1), heartbeat INTEGER NOT NULL, ready INTEGER NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL REFERENCES users(id),
 action TEXT NOT NULL, target TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS download_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id), key_id TEXT REFERENCES api_keys(id),
 program TEXT NOT NULL, filename TEXT NOT NULL, source TEXT NOT NULL, created_at INTEGER NOT NULL
);
"""
SCOPES = {'download:' + program for program in PROGRAMS}


def register_portal(app, db, fail, payload, text, require_user, rate_limit, admins):
    def now():
        return int(time.time())

    def admin():
        require_user()
        if g.user['id'] not in admins:
            abort(403)

    def clean_name(value, maximum=40):
        value = text(value).strip()
        if not 2 <= len(value) <= maximum or any(ord(c) < 32 for c in value):
            abort(400, description='이름을 확인해 주세요.')
        return value

    def auto_approved(user_id):
        permission = db().execute('SELECT approved FROM rental_permissions WHERE user_id=?', (user_id,)).fetchone()
        return user_id in admins or bool(permission and permission['approved'])

    def runtime():
        row = db().execute('SELECT * FROM rental_runtime WHERE id=1').fetchone()
        healthy = bool(row and row['ready'] and row['heartbeat'] >= now() - 90)
        return {'ready': healthy, 'message': '자동 생성 서비스 정상' if healthy else '자동 생성 서비스를 확인 중입니다.'}

    def key_json(row):
        return {key: row[key] for key in ('id', 'name', 'prefix', 'created_at', 'expires_at', 'revoked_at', 'last_used_at', 'use_count')} | {'scopes': json.loads(row['scopes'])}

    def rental_json(row):
        result = {key: row[key] for key in ('id', 'user_id', 'name', 'plan', 'status', 'created_at', 'updated_at', 'approved_at', 'expires_at', 'last_error')}
        result['sshFingerprint'] = row['ssh_fingerprint']
        result['sshHost'] = os.getenv('RENTAL_SSH_HOST', '100.110.205.65')
        result['sshUser'] = 'tenant'
        result['sshPort'] = row['ssh_port'] if row['status'] in ('running', 'stopped') else None
        result['actions'] = [action for action, states in TRANSITIONS.items() if row['status'] in states]
        if row['status'] == 'pending':
            result['actions'] = ['cancel']
        return result

    def audit(action, target):
        db().execute('INSERT INTO admin_events(actor_id,action,target,created_at) VALUES(?,?,?,?)',
                     (g.user['id'], action, target, now()))

    def enqueue(rental_id, action):
        db().execute("INSERT INTO rental_jobs(id,rental_id,action,status,created_at) VALUES(?,?,?,'queued',?)",
                     (secrets.token_hex(16), rental_id, action, now()))

    def reserve(row):
        placeholders = ','.join('?' for _ in RESERVED)
        count = db().execute(f'SELECT count(*) FROM rentals WHERE status IN ({placeholders})', RESERVED).fetchone()[0]
        if count >= capacity_limit():
            return False
        db().execute("UPDATE rentals SET status='queued',approved_by=?,approved_at=?,updated_at=?,last_error=NULL WHERE id=?",
                     (g.user['id'], now(), now(), row['id']))
        enqueue(row['id'], 'create')
        return True

    @app.get('/api/services')
    def services():
        require_user()
        return jsonify(autoApproved=auto_approved(g.user['id']), isAdmin=g.user['id'] in admins,
                       runtime=runtime(), plan=PLAN, capacity=capacity_limit(), maxKeys=5,
                       programs=catalog(app.config['SITE_ROOT']))

    @app.get('/api/programs')
    def programs():
        return jsonify(programs=catalog(app.config['SITE_ROOT']))

    @app.get('/api/keys')
    def keys():
        require_user()
        return jsonify(keys=[key_json(row) for row in db().execute('SELECT * FROM api_keys WHERE user_id=? ORDER BY created_at DESC LIMIT 100', (g.user['id'],))])

    @app.post('/api/keys')
    def create_key():
        require_user()
        data = payload()
        name = clean_name(data.get('name'))
        program = data.get('program')
        scopes = ['download:' + program] if isinstance(program, str) and program in PROGRAMS else []
        days = data.get('days', 30)
        if not scopes or 'scopes' in data:
            return fail('다운로드할 프로그램 한 개를 선택해 주세요.')
        if type(days) is not int or days not in (7, 30, 90):
            return fail('유효기간은 7일, 30일, 90일 중 선택해 주세요.')
        if not rate_limit('key-create', 15, 3600, g.user['id']):
            return fail('키 발급 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        key_id = secrets.token_hex(16)
        secret = 'hb_live_' + secrets.token_urlsafe(32)
        with db():
            db().execute('BEGIN IMMEDIATE')
            count = db().execute('SELECT count(*) FROM api_keys WHERE user_id=? AND revoked_at IS NULL AND expires_at>?', (g.user['id'], now())).fetchone()[0]
            if count >= 5:
                return fail('활성 API 키는 최대 5개입니다. 기존 키를 폐기해 주세요.', 409)
            db().execute('INSERT INTO api_keys(id,user_id,name,token_hash,prefix,scopes,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                         (key_id, g.user['id'], name, hashlib.sha256(secret.encode()).hexdigest(), secret[:15] + '…', json.dumps(sorted(set(scopes))), now(), now() + days * 86400))
        row = db().execute('SELECT * FROM api_keys WHERE id=?', (key_id,)).fetchone()
        return jsonify(key=key_json(row), secret=secret), 201

    @app.delete('/api/keys/<key_id>')
    def revoke_key(key_id):
        require_user()
        with db():
            result = db().execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND user_id=?', (now(), key_id, g.user['id']))
            if not result.rowcount:
                abort(404)
        return jsonify(ok=True)

    def api_key(scope):
        def decorate(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                value = request.headers.get('Authorization', '')
                if not value.startswith('Bearer hb_live_') or len(value) > 128:
                    return fail('유효한 Bearer API 키가 필요합니다.', 401)
                hashed = hashlib.sha256(value[7:].encode()).hexdigest()
                row = db().execute('SELECT * FROM api_keys WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?', (hashed, now())).fetchone()
                if not row:
                    return fail('만료되었거나 폐기된 API 키입니다.', 401)
                if scope not in json.loads(row['scopes']):
                    return fail('이 API를 사용할 권한이 없는 키입니다.', 403)
                if not rate_limit('public-api', 60, 60, row['id']):
                    return fail('API 키당 분당 60회까지 요청할 수 있습니다.', 429)
                g.api_user_id = row['user_id']
                g.api_key_id = row['id']
                with db():
                    db().execute('UPDATE api_keys SET last_used_at=?,use_count=use_count+1 WHERE id=?', (now(), row['id']))
                return func(*args, **kwargs)
            return wrapped
        return decorate

    @app.get('/api/v1/programs/<program>')
    def api_program(program):
        if program not in PROGRAMS:
            abort(404)
        @api_key('download:' + program)
        def details():
            return jsonify(program=next(row for row in catalog(app.config['SITE_ROOT']) if row['id'] == program))
        return details()

    def download(program, filename, from_api=False):
        file = resolve_file(app.config['SITE_ROOT'], program, filename)
        if not file:
            abort(404)
        user_id = g.api_user_id if from_api else g.user['id']
        key_id = g.api_key_id if from_api else None
        if not rate_limit('download', 60, 3600, key_id or user_id):
            return fail('다운로드는 시간당 60회까지 이용할 수 있습니다.', 429)
        if request.method != 'HEAD':
            with db():
                db().execute('INSERT INTO download_events(user_id,key_id,program,filename,source,created_at) VALUES(?,?,?,?,?,?)',
                             (user_id, key_id, program, filename, 'api' if from_api else 'site', now()))
        return send_file(file, as_attachment=True, download_name=filename, conditional=True)

    @app.get('/api/v1/programs/<program>/files/<filename>')
    def api_download(program, filename):
        if program not in PROGRAMS or filename not in PROGRAMS[program]['files']:
            abort(404)
        @api_key('download:' + program)
        def send():
            return download(program, filename, True)
        return send()

    @app.get('/api/v1/programs/<program>/download')
    def api_default_download(program):
        if program not in PROGRAMS:
            abort(404)
        return api_download(program, PROGRAMS[program]['defaultFile'])

    @app.get('/downloads/<filename>')
    def site_download(filename):
        if filename == 'manifest.json':
            return send_from_directory(Path(app.config['SITE_ROOT']) / 'downloads', filename)
        program = next((key for key, value in PROGRAMS.items() if filename in value['files']), None)
        if program is None:
            abort(404)
        if not g.user:
            return redirect('/api.html?download=' + program)
        return download(program, filename)

    @app.get('/api/rentals')
    def rentals():
        require_user()
        return jsonify(rentals=[rental_json(row) for row in db().execute('SELECT * FROM rentals WHERE user_id=? ORDER BY created_at DESC LIMIT 50', (g.user['id'],))])

    @app.post('/api/rentals')
    def request_rental():
        require_user()
        data = payload()
        name = clean_name(data.get('name'))
        try:
            public_key = validate_public_key(data.get('publicKey'))
        except ValueError as error:
            return fail(str(error))
        if data.get('plan', PLAN['id']) != PLAN['id']:
            return fail('지원하지 않는 서버 유형입니다.')
        if not rate_limit('rental-create', 10, 86400, g.user['id']):
            return fail('대여 신청 횟수를 초과했습니다.', 429)
        rental_id = secrets.token_hex(16)
        with db():
            db().execute('BEGIN IMMEDIATE')
            terminal = ','.join('?' for _ in TERMINAL)
            if db().execute(f'SELECT 1 FROM rentals WHERE user_id=? AND status NOT IN ({terminal})', (g.user['id'], *TERMINAL)).fetchone():
                return fail('진행 중인 대여는 계정당 1개입니다.', 409)
            db().execute("INSERT INTO rentals(id,user_id,name,plan,public_key,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)", (rental_id, g.user['id'], name, PLAN['id'], public_key, now(), now()))
            if auto_approved(g.user['id']):
                if not runtime()['ready']:
                    db().rollback()
                    return fail('자동 생성 서비스를 확인 중입니다. 잠시 후 다시 신청해 주세요.', 503)
                row = db().execute('SELECT * FROM rentals WHERE id=?', (rental_id,)).fetchone()
                if not reserve(row):
                    db().rollback()
                    return fail('현재 대여 가능한 서버 자원이 모두 사용 중입니다.', 409)
        return jsonify(rental=rental_json(db().execute('SELECT * FROM rentals WHERE id=?', (rental_id,)).fetchone())), 201

    @app.post('/api/rentals/<rental_id>/actions')
    def rental_action(rental_id):
        require_user()
        action = payload().get('action')
        with db():
            db().execute('BEGIN IMMEDIATE')
            row = db().execute('SELECT * FROM rentals WHERE id=?', (rental_id,)).fetchone()
            if not row or (row['user_id'] != g.user['id'] and g.user['id'] not in admins):
                abort(404)
            if row['expires_at'] and row['expires_at'] <= now() and action not in ('terminate', 'cancel'):
                return fail('대여 시간이 만료되어 종료 처리 중입니다.', 409)
            if action == 'cancel' and row['status'] == 'pending':
                db().execute("UPDATE rentals SET status='cancelled',updated_at=? WHERE id=?", (now(), rental_id))
            else:
                if not isinstance(action, str) or row['status'] not in TRANSITIONS.get(action, ()):
                    return fail('현재 상태에서는 이 작업을 할 수 없습니다.', 409)
                target = {'start': 'starting', 'stop': 'stopping', 'restart': 'restarting', 'terminate': 'terminating', 'retry': 'queued'}[action]
                db().execute("UPDATE rental_jobs SET status='cancelled' WHERE rental_id=? AND status='queued'", (rental_id,))
                db().execute('UPDATE rentals SET status=?,updated_at=?,last_error=NULL WHERE id=?', (target, now(), rental_id))
                enqueue(rental_id, 'create' if action == 'retry' else action)
            if g.user['id'] in admins:
                audit('rental:' + str(action), rental_id)
        return jsonify(ok=True)

    @app.get('/api/admin/overview')
    def admin_overview():
        admin()
        query = request.args.get('q', '').strip()[:80]
        users = db().execute('''SELECT u.id,u.display_name,u.email,u.created_at,COALESCE(p.approved,0) AS auto_approved,
          (SELECT group_concat(provider) FROM identities WHERE user_id=u.id) AS providers
          FROM users u LEFT JOIN rental_permissions p ON p.user_id=u.id
          WHERE u.id LIKE ? OR u.display_name LIKE ? OR u.email LIKE ? ORDER BY u.created_at DESC LIMIT 50''', tuple('%' + query + '%' for _ in range(3))).fetchall()
        rental_rows = db().execute('''SELECT r.*,u.display_name FROM rentals r JOIN users u ON u.id=r.user_id
          ORDER BY CASE WHEN r.status='pending' THEN 0 ELSE 1 END, r.created_at DESC LIMIT 100''').fetchall()
        return jsonify(users=[dict(row) | {'isAdmin': row['id'] in admins} for row in users],
                       rentals=[rental_json(row) | {'ownerName': row['display_name']} for row in rental_rows], runtime=runtime(), capacity=capacity_limit())

    @app.post('/api/admin/users/<user_id>/rental-access')
    def approve_account(user_id):
        admin()
        approved = payload().get('approved')
        if type(approved) is not bool:
            return fail('승인 여부가 필요합니다.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            if not db().execute('SELECT 1 FROM users WHERE id=?', (user_id,)).fetchone():
                abort(404)
            pending = db().execute("SELECT * FROM rentals WHERE user_id=? AND status='pending' ORDER BY created_at", (user_id,)).fetchall()
            if approved and pending and not runtime()['ready']:
                return fail('자동 생성 서비스를 확인한 뒤 승인해 주세요.', 503)
            for row in pending if approved else []:
                if not reserve(row):
                    db().rollback()
                    return fail('서버 자원이 모두 사용 중이어서 승인하지 못했습니다.', 409)
            db().execute('INSERT INTO rental_permissions VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET approved=excluded.approved,updated_by=excluded.updated_by,updated_at=excluded.updated_at', (user_id, int(approved), g.user['id'], now()))
            audit('account:approve' if approved else 'account:revoke', user_id)
        return jsonify(ok=True)

    @app.post('/api/admin/rentals/<rental_id>/review')
    def review_rental(rental_id):
        admin()
        decision = payload().get('decision')
        if decision not in ('approve', 'reject'):
            return fail('승인 또는 거절을 선택해 주세요.')
        with db():
            db().execute('BEGIN IMMEDIATE')
            row = db().execute("SELECT * FROM rentals WHERE id=? AND status='pending'", (rental_id,)).fetchone()
            if not row:
                return fail('이미 처리되었거나 없는 대여 신청입니다.', 409)
            if decision == 'approve':
                if not runtime()['ready']:
                    return fail('자동 생성 서비스를 확인한 뒤 승인해 주세요.', 503)
                if not reserve(row):
                    return fail('현재 대여 가능한 서버 자원이 모두 사용 중입니다.', 409)
            else:
                db().execute("UPDATE rentals SET status='rejected',updated_at=? WHERE id=?", (now(), rental_id))
            audit('request:' + decision, rental_id)
        return jsonify(ok=True)
