"""Same-origin membership and page comments for the existing static site."""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
SESSION_TTL = 60 * 60 * 24 * 7
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
 token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires_at INTEGER NOT NULL
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
"""


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
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32:
        raise RuntimeError('SECRET_KEY must be at least 32 characters')
    base = urlsplit(app.config['BASE_URL'])
    if base.scheme not in ('http', 'https') or not base.hostname or base.path or base.query or base.fragment:
        raise RuntimeError('BASE_URL must be an origin without a path')
    secure = base.scheme == 'https'
    cookie_name = '__Host-habang_sid' if secure else 'habang_sid'
    app.config.update(
        SESSION_COOKIE_SECURE=secure,
        SESSION_COOKIE_NAME='__Host-habang_oauth' if secure else 'habang_oauth',
        TRUSTED_HOSTS=[base.hostname, 'localhost', '127.0.0.1'],
    )
    root = Path(app.config['SITE_ROOT']).resolve()
    pages = {'/' + p.name for p in root.glob('*.html')}
    admins = set(app.config['ADMIN_USER_IDS'].split(',')) - {''}
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
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

    def new_session(user_id=None):
        if getattr(g, 'token', None):
            db().execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(g.token),))
        g.token = secrets.token_urlsafe(32)
        db().execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(g.token), user_id, int(time.time()) + SESSION_TTL))
        db().execute('DELETE FROM sessions WHERE expires_at < ?', (int(time.time()),))
        db().execute('DELETE FROM rate_limits WHERE expires_at < ?', (int(time.time()),))
        db().commit()
        g.cookie_changed = True
        g.user = db().execute('SELECT id, display_name FROM users WHERE id=?', (user_id,)).fetchone() if user_id else None

    @app.before_request
    def prepare_session():
        g.user = None
        g.token = request.cookies.get(cookie_name, '')
        g.cookie_changed = False
        if not (request.path.startswith('/api/') or request.path.startswith('/auth/')):
            return
        stored = db().execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?',
                              (token_hash(g.token), int(time.time()))).fetchone() if g.token else None
        if stored:
            g.user = db().execute('SELECT id, display_name FROM users WHERE id=?', (stored['user_id'],)).fetchone()
        elif request.path == '/api/session' or request.path.startswith('/auth/'):
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
        if request.path.startswith(('/api/', '/auth/')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Cookie'
        if getattr(g, 'cookie_changed', False):
            response.set_cookie(cookie_name, g.token, max_age=SESSION_TTL, secure=secure,
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
        return {'id': g.user['id'], 'name': g.user['display_name']} if g.user else None

    def require_user():
        if not g.user:
            abort(401, description='로그인 후 이용해 주세요.')

    @app.get('/api/session')
    def current_session():
        return jsonify(user=public_user(), csrfToken=csrf_token(), providers={
            name: bool(oauth.create_client(name)) for name in ('google', 'github')
        })

    @app.post('/api/auth/register')
    def register():
        if not rate_limit('signup', 5, 3600):
            return fail('가입 요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
        data = payload()
        email = text(data.get('email')).strip().lower()
        name = text(data.get('name')).strip()
        password = text(data.get('password'))
        if len(email) > 254 or not EMAIL.fullmatch(email):
            return fail('올바른 이메일 주소를 입력해 주세요.')
        if not 2 <= len(name) <= 30 or any(ord(c) < 32 for c in name):
            return fail('닉네임은 2~30자로 입력해 주세요.')
        if not 12 <= len(password) <= 128:
            return fail('비밀번호는 12~128자로 입력해 주세요.')
        hashed = PASSWORDS.hash(password)
        user_id = secrets.token_hex(16)
        try:
            with db():
                db().execute('INSERT INTO users VALUES(?,?,?,?,?)', (user_id, email, hashed, name, int(time.time())))
        except sqlite3.IntegrityError:
            return fail('이미 가입된 이메일입니다. 로그인해 주세요.', 409)
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

    @app.get('/auth/<provider>')
    def oauth_begin(provider):
        if provider not in ('google', 'github'):
            abort(404)
        client = oauth.create_client(provider)
        if not client:
            return redirect('/?auth_error=unavailable')
        if not rate_limit('oauth', 30, 300):
            return fail('요청이 많습니다. 잠시 후 다시 시도해 주세요.', 429)
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
            name = ''.join(c for c in str(name) if ord(c) >= 32).strip()[:30] or '회원'
            # Never merge accounts by email: a provider subject is the identity key.
            with db():
                db().execute('BEGIN IMMEDIATE')
                identity = db().execute('SELECT user_id FROM identities WHERE provider=? AND subject=?', (provider, subject)).fetchone()
                user_id = identity['user_id'] if identity else secrets.token_hex(16)
                if not identity:
                    db().execute('INSERT INTO users VALUES(?,NULL,NULL,?,?)', (user_id, name, int(time.time())))
                    db().execute('INSERT INTO identities VALUES(?,?,?,?)', (provider, subject, user_id, email))
            session.clear()
            new_session(user_id)
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
                   or (parts[0] in ('images', 'downloads') and Path(path).suffix.lower() in
                       ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.ico', '.cmd', '.zip', '.sh', '.json', '.apk')))
        if not allowed:
            abort(404)
        return send_from_directory(root, path)

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=8080, debug=False)
