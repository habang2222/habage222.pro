import os
import hashlib
import hmac
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from app import ANON_SESSION_TTL, PASSWORDS, create_app


class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = dict(TESTING=True, SECRET_KEY='integration-test-secret-' * 3,
                           BASE_URL='https://test.example',
                           DATABASE=str(Path(self.temp.name) / 'test.sqlite3'),
                           SITE_ROOT=os.getenv('SITE_ROOT', str(Path(__file__).resolve().parents[1])),
                           GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='',
                           GITHUB_CLIENT_ID='', GITHUB_CLIENT_SECRET='')
        self.config['TRUST_PROXY'] = False
        self.config['ALIAS_HOSTS'] = ''
        self.config['SMTP_HOST'] = 'smtp.test.invalid'
        self.config['SMTP_FROM'] = 'noreply@test.example'
        self.mail = []
        self.mail_patch = patch('app.send_verification_email', side_effect=lambda _config, email, code: self.mail.append((email, code)))
        self.mail_patch.start()
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.csrf = self.start(self.client)

    def tearDown(self):
        self.mail_patch.stop()
        self.temp.cleanup()

    def start(self, client):
        res = client.get('/api/session', base_url='https://test.example')
        self.assertEqual(res.status_code, 200)
        return res.json['csrfToken']

    def write(self, path, data, client=None, csrf=None, method='POST'):
        return (client or self.client).open(path, method=method, json=data,
            base_url='https://test.example', headers={'Origin': 'https://test.example',
            'X-CSRF-Token': self.csrf if csrf is None else csrf})

    def verify_address(self, email='member@example.com', client=None, csrf=None):
        started = self.write('/api/auth/email/start', {'email': email}, client=client, csrf=csrf)
        self.assertEqual(started.status_code, 202, started.json)
        self.assertEqual(self.mail[-1][0], email.lower())
        checked = self.write('/api/auth/email/verify', {'email': email, 'code': self.mail[-1][1]}, client=client, csrf=csrf)
        self.assertEqual(checked.status_code, 200, checked.json)
        return checked

    def signup(self, email='member@example.com', name='테스트 회원', client=None, csrf=None):
        self.verify_address(email, client=client, csrf=csrf)
        res = self.write('/api/auth/register', {'email': email, 'name': name,
            'fullName': '테스트 이름', 'password': 'correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(res.status_code, 201, res.json)
        if client is None:
            self.csrf = res.json['csrfToken']
        return res

    def test_registration_login_and_session_revocation(self):
        anonymous_cookie = self.client.get_cookie('__Host-habang_sid', domain='test.example').value
        res = self.signup()
        self.assertNotEqual(anonymous_cookie, self.client.get_cookie('__Host-habang_sid', domain='test.example').value)
        cookie = self.client.get_cookie('__Host-habang_sid', domain='test.example')
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        with closing(sqlite3.connect(self.config['DATABASE'])) as db:
            row = db.execute('SELECT email,password_hash FROM users').fetchone()
        self.assertEqual(row[0], 'member@example.com')
        self.assertTrue(row[1].startswith('$argon2id$'))
        logged_in_cookie = cookie.value
        self.csrf = self.write('/api/auth/logout', {}).json['csrfToken']
        replay = self.app.test_client()
        replay.set_cookie('__Host-habang_sid', logged_in_cookie, domain='test.example')
        self.assertIsNone(replay.get('/api/session', base_url='https://test.example').json['user'])
        self.assertEqual(self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'incorrect'}).status_code, 401)
        res = self.write('/api/auth/login', {'email': 'MEMBER@EXAMPLE.COM', 'password': 'correct horse battery staple'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['user']['name'], '테스트 회원')
        self.assertTrue(res.json['user']['verified'])
        self.assertTrue(res.json['user']['registrationComplete'])

    def test_csrf_and_origin_are_required(self):
        data = {'email': 'member@example.com', 'name': '회원', 'password': 'correct horse battery staple'}
        res = self.client.post('/api/auth/register', json=data, base_url='https://test.example')
        self.assertEqual(res.status_code, 403)
        res = self.client.post('/api/auth/register', json=data, base_url='https://test.example',
            headers={'Origin': 'https://evil.example', 'X-CSRF-Token': self.csrf})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.write('/api/auth/register', data, csrf='wrong').status_code, 403)
        stale = self.csrf
        self.signup()
        self.assertEqual(self.write('/api/auth/logout', {}, csrf=stale).status_code, 403)

    def test_comments_are_persistent_scoped_and_owner_only(self):
        self.assertEqual(self.write('/api/comments', {'page': '/', 'body': 'anonymous'}).status_code, 401)
        self.signup()
        first = self.write('/api/comments', {'page': '/index.html', 'body': '<script>alert(1)</script>\n질문입니다'}).json['comment']
        self.assertEqual(first['body'], '<script>alert(1)</script>\n질문입니다')
        self.assertNotIn('email', first)
        self.write('/api/comments', {'page': '/guide.html', 'body': '다른 페이지'})
        listing = self.client.get('/api/comments?page=/', base_url='https://test.example').json
        self.assertEqual(listing['total'], 1)
        self.assertTrue(listing['comments'][0]['canEdit'])
        other = self.app.test_client()
        other_csrf = self.start(other)
        res = self.signup(email='other@example.com', name='다른 회원', client=other, csrf=other_csrf)
        other_csrf = res.json['csrfToken']
        for method in ('PATCH', 'DELETE'):
            res = self.write(f'/api/comments/{first["id"]}', {'body': 'not yours'}, client=other, csrf=other_csrf, method=method)
            self.assertEqual(res.status_code, 403)
        res = self.write(f'/api/comments/{first["id"]}', {'body': '수정한 댓글'}, method='PATCH')
        self.assertEqual(res.json['comment']['body'], '수정한 댓글')
        restarted = create_app(self.config).test_client()
        self.assertEqual(restarted.get('/api/comments?page=/', base_url='https://test.example').json['total'], 1)
        self.assertEqual(self.write(f'/api/comments/{first["id"]}', {}, method='DELETE').status_code, 200)
        self.assertEqual(self.client.get('/api/comments?page=/', base_url='https://test.example').json['total'], 0)

    def test_validation_and_rate_limits(self):
        self.assertEqual(self.write('/api/auth/register', {'name': '회원', 'email': 'member@example.com', 'fullName': '테스트 이름', 'password': 'a' * 12}).status_code, 403)
        self.verify_address()
        for name, email, full_name, password, expected in [
            ('a', 'member@example.com', '테스트 이름', 'a' * 12, 400),
            ('valid', 'bad', '테스트 이름', 'a' * 12, 403),
            ('valid', 'member@example.com', 'a', 'a' * 12, 400),
            ('valid', 'member@example.com', '테스트 이름', 'short', 400),
        ]:
            self.assertEqual(self.write('/api/auth/register', {'name': name, 'email': email, 'fullName': full_name, 'password': password}).status_code, expected)
        registered = self.write('/api/auth/register', {'name': '테스트 회원', 'email': 'member@example.com', 'fullName': '테스트 이름', 'password': 'correct horse battery staple'})
        self.assertEqual(registered.status_code, 201)
        self.csrf = registered.json['csrfToken']
        self.assertEqual(self.write('/api/comments', {'page': '/missing.html', 'body': 'test'}).status_code, 404)
        self.assertEqual(self.write('/api/comments', {'page': '/', 'body': ' '}).status_code, 400)
        self.assertEqual(self.write('/api/comments', {'page': '/', 'body': 'a' * 2001}).status_code, 400)
        for i in range(10):
            self.assertEqual(self.write('/api/comments', {'page': '/', 'body': f'comment {i}'}).status_code, 201)
        self.assertEqual(self.write('/api/comments', {'page': '/', 'body': 'too fast'}).status_code, 429)

    def test_static_files_are_allowlisted_and_all_pages_have_comments(self):
        for path in ('/.env', '/server/app.py', '/server/.env', '/data/community.sqlite3', '/.git/config', '/CNAME', '/README.md', '/images/../../server/app.py'):
            self.assertEqual(self.client.get(path, base_url='https://test.example').status_code, 404, path)
        pages = list(Path(self.config['SITE_ROOT']).glob('*.html'))
        self.assertGreaterEqual(len(pages), 6)
        for page in pages:
            res = self.client.get('/' + page.name, base_url='https://test.example')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'/community.js?v=4', res.data)
            self.assertIn(b'/community.css?v=', res.data)
            res.close()
        res = self.client.get('/community.js', base_url='https://test.example')
        self.assertNotIn(b'innerHTML', res.data)
        self.assertIn("script-src 'self'", res.headers['Content-Security-Policy'])
        self.assertEqual(res.headers['X-Content-Type-Options'], 'nosniff')
        res.close()

    def test_email_challenge_is_required_hashed_limited_and_disabled_without_mail(self):
        missing = create_app({**self.config, 'SMTP_HOST': '', 'SMTP_FROM': ''}).test_client()
        csrf = self.start(missing)
        self.assertFalse(missing.get('/api/session', base_url='https://test.example').json['emailVerificationAvailable'])
        self.assertEqual(self.write('/api/auth/email/start', {'email': 'other@example.com'}, client=missing, csrf=csrf).status_code, 503)
        self.assertEqual(self.write('/api/auth/register', {'email': 'other@example.com', 'name': '회원', 'fullName': '테스트 이름', 'password': 'a' * 12}, client=missing, csrf=csrf).status_code, 403)
        self.assertEqual(self.write('/api/auth/email/start', {'email': 'member@example.com'}).status_code, 202)
        code = self.mail[-1][1]
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            stored = connection.execute('SELECT code_hash FROM email_challenges WHERE email=?', ('member@example.com',)).fetchone()[0]
        self.assertNotEqual(stored, code)
        for _ in range(5):
            self.assertEqual(self.write('/api/auth/email/verify', {'email': 'member@example.com', 'code': '00000000'}).status_code, 400)
        self.assertEqual(self.write('/api/auth/email/verify', {'email': 'member@example.com', 'code': code}).status_code, 400)
        self.assertEqual(self.write('/api/auth/email/start', {'email': 'member@example.com'}).status_code, 202)
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            connection.execute('UPDATE email_challenges SET expires_at=0 WHERE email=?', ('member@example.com',))
            connection.commit()
        self.assertEqual(self.write('/api/auth/email/verify', {'email': 'member@example.com', 'code': self.mail[-1][1]}).status_code, 400)

    def test_anonymous_sessions_are_short_lived_stateless_and_rate_limited(self):
        cookie = self.client.get_cookie('__Host-habang_sid', domain='test.example').value
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
        response = self.client.get('/api/session', base_url='https://test.example')
        self.assertEqual(self.client.get_cookie('__Host-habang_sid', domain='test.example').value, cookie)
        self.assertNotIn('Set-Cookie', response.headers)
        expired_raw = f'a.{int(time.time()) - ANON_SESSION_TTL - 1}.expired'
        signature = hmac.new(self.config['SECRET_KEY'].encode(), expired_raw.encode(), hashlib.sha256).hexdigest()
        self.client.set_cookie('__Host-habang_sid', expired_raw + '.' + signature, domain='test.example')
        refreshed = self.client.get('/api/session', base_url='https://test.example')
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn('Max-Age=1800', refreshed.headers['Set-Cookie'])
        self.assertNotEqual(self.client.get_cookie('__Host-habang_sid', domain='test.example').value, cookie)
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
        for _ in range(298):
            self.assertEqual(self.app.test_client().get('/api/session', base_url='https://test.example').status_code, 200)
        self.assertEqual(self.app.test_client().get('/api/session', base_url='https://test.example').status_code, 429)
        self.assertEqual(self.app.test_client().get('/api/session', base_url='https://test.example', environ_overrides={'REMOTE_ADDR': '198.51.100.2'}).status_code, 200)

    def test_legacy_admin_recovers_by_explicit_oauth_link_without_losing_id(self):
        old_db = str(Path(self.temp.name) / 'legacy.sqlite3')
        legacy_id = 'legacy-admin'
        with closing(sqlite3.connect(old_db)) as connection:
            connection.execute('CREATE TABLE users (id TEXT PRIMARY KEY,email TEXT UNIQUE COLLATE NOCASE,password_hash TEXT,display_name TEXT NOT NULL,created_at INTEGER NOT NULL)')
            connection.execute('CREATE TABLE sessions (token_hash TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires_at INTEGER NOT NULL)')
            connection.execute('INSERT INTO users VALUES(?,?,?,?,?)', (legacy_id, 'legacy@example.com', PASSWORDS.hash('old correct horse battery staple'), '관리자', int(time.time())))
            connection.execute('INSERT INTO sessions VALUES(?,?,?)', ('old-anonymous', None, int(time.time()) + 86400))
            connection.commit()
        app = create_app({**self.config, 'DATABASE': old_db, 'ADMIN_USER_IDS': legacy_id,
                          'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'})
        with closing(sqlite3.connect(old_db)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM sessions').fetchone()[0], 0)
        client = app.test_client()
        csrf = self.start(client)
        login = self.write('/api/auth/login', {'email': 'legacy@example.com', 'password': 'old correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(login.json['user']['id'], legacy_id)
        self.assertFalse(login.json['user']['verified'])
        self.assertEqual(client.get('/api/admin/overview', base_url='https://test.example').status_code, 403)
        self.assertEqual(self.write('/api/auth/link/google', {'next': '/'}, client=client, csrf=login.json['csrfToken']).status_code, 200)
        provider = app.extensions['authlib.integrations.flask_client'].create_client('google')
        with patch.object(provider, 'authorize_access_token', return_value={'userinfo': {
            'sub': 'google-legacy-admin', 'email': 'legacy@example.com', 'email_verified': True, 'name': '관리자'}}):
            self.assertEqual(client.get('/auth/google/callback', base_url='https://test.example').location, '/')
        self.assertEqual(client.get('/api/session', base_url='https://test.example').json['pendingRegistration']['email'], 'legacy@example.com')
        complete = self.write('/api/auth/register', {'email': 'legacy@example.com', 'name': '관리자',
            'fullName': '관리자 이름', 'password': 'new correct horse battery staple'}, client=client, csrf=login.json['csrfToken'])
        self.assertEqual(complete.status_code, 201, complete.json)
        self.assertEqual(complete.json['user']['id'], legacy_id)
        self.assertEqual(client.get('/api/admin/overview', base_url='https://test.example').status_code, 200)
        with closing(sqlite3.connect(old_db)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0], 1)
            connection.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)', ('expired-authenticated', legacy_id, 0))
            connection.commit()
        csrf = complete.json['csrfToken']
        self.assertEqual(self.write('/api/auth/logout', {}, client=client, csrf=csrf).status_code, 200)
        relogin = self.write('/api/auth/login', {'email': 'legacy@example.com', 'password': 'new correct horse battery staple'}, client=client,
                             csrf=self.start(client))
        self.assertEqual(relogin.status_code, 200)
        with closing(sqlite3.connect(old_db)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM sessions WHERE token_hash=?', ('expired-authenticated',)).fetchone()[0], 0)

    def test_oauth_is_disabled_until_credentials_are_configured(self):
        res = self.client.get('/api/session', base_url='https://test.example')
        self.assertEqual(res.json['providers'], {'google': False, 'github': False})
        self.assertEqual(self.client.get('/auth/google', base_url='https://test.example').location, '/?auth_error=unavailable')
        self.assertEqual(self.client.get('/auth/unknown', base_url='https://test.example').status_code, 404)

    def test_oauth_state_and_return_path(self):
        app = create_app({**self.config, 'GITHUB_CLIENT_ID': 'test-id', 'GITHUB_CLIENT_SECRET': 'test-secret'})
        client = app.test_client()
        res = client.get('/auth/github?next=https://evil.example', base_url='https://test.example')
        self.assertEqual(res.status_code, 302)
        self.assertIn('code_challenge=', res.location)
        self.assertIn('state=', res.location)
        self.assertNotIn('evil.example', res.location)
        res = client.get('/auth/github/callback?code=fake&state=invalid', base_url='https://test.example')
        self.assertEqual(res.location, '/?auth_error=failed')
        self.assertIsNone(client.get('/api/session', base_url='https://test.example').json['user'])

    def test_github_requires_a_verified_primary_email_before_signup(self):
        app = create_app({**self.config, 'GITHUB_CLIENT_ID': 'test-id', 'GITHUB_CLIENT_SECRET': 'test-secret'})
        client = app.test_client()
        provider = app.extensions['authlib.integrations.flask_client'].create_client('github')
        user = Mock(); user.json.return_value = {'id': 42, 'name': 'Github 회원'}
        def callback(emails):
            email_response = Mock(); email_response.json.return_value = emails
            with patch.object(provider, 'authorize_access_token', return_value={'access_token': 'test-token'}), \
                 patch.object(provider, 'get', side_effect=[user, email_response]):
                return client.get('/auth/github/callback', base_url='https://test.example')
        self.assertEqual(callback([{'email': 'github@example.com', 'primary': True, 'verified': False}]).location, '/?auth_error=failed')
        self.assertIsNone(client.get('/api/session', base_url='https://test.example').json['pendingRegistration'])
        self.assertEqual(callback([{'email': 'github@example.com', 'primary': True, 'verified': True}]).location, '/')
        pending = client.get('/api/session', base_url='https://test.example').json['pendingRegistration']
        self.assertEqual(pending['email'], 'github@example.com')
        self.assertEqual(pending['provider'], 'github')
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_verified_signup_proof_expires(self):
        self.verify_address()
        with patch('app.PROOF_TTL', -1):
            attempt = self.write('/api/auth/register', {'email': 'member@example.com', 'name': '회원',
                'fullName': '테스트 이름', 'password': 'correct horse battery staple'})
        self.assertEqual(attempt.status_code, 403)
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_login_limit_survives_restarts(self):
        for _ in range(10):
            self.assertEqual(self.write('/api/auth/login', {'email': 'nobody@example.com', 'password': 'wrong'}).status_code, 401)
        app = create_app(self.config)
        client = app.test_client()
        csrf = self.start(client)
        self.assertEqual(self.write('/api/auth/login', {'email': 'nobody@example.com', 'password': 'wrong'}, client=client, csrf=csrf).status_code, 429)

    def test_pagination_does_not_skip_or_repeat_comments(self):
        member_id = self.signup().json['user']['id']
        with closing(sqlite3.connect(self.config['DATABASE'])) as db:
            db.executemany('INSERT INTO comments(page,user_id,body,created_at,updated_at) VALUES(?,?,?,?,?)',
                           [('/', member_id, str(i), i, i) for i in range(25)])
            db.commit()
        first = self.client.get('/api/comments?page=/', base_url='https://test.example').json
        second = self.client.get(f'/api/comments?page=/&before={first["nextBefore"]}', base_url='https://test.example').json
        self.assertEqual(first['total'], 25)
        self.assertEqual(len(first['comments']), 20)
        self.assertEqual(len(second['comments']), 5)
        self.assertIsNone(second['nextBefore'])
        self.assertEqual(len({c['id'] for c in first['comments'] + second['comments']}), 25)

    def test_provider_subject_identity_does_not_merge_by_email(self):
        local_id = self.signup().json['user']['id']
        app = create_app({**self.config, 'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'})
        client = app.test_client()
        provider = app.extensions['authlib.integrations.flask_client'].create_client('google')
        def callback(subject, email='member@example.com', verified=True):
            # Mock only the provider boundary; state/PKCE failure has a separate real-library test.
            info = dict(sub=subject, email=email, email_verified=verified, name='소셜 회원')
            with patch.object(provider, 'authorize_access_token', return_value={'userinfo': info}):
                response = client.get('/auth/google/callback', base_url='https://test.example')
            return response, client.get('/api/session', base_url='https://test.example').json
        conflict, state = callback('provider-user-1')
        self.assertEqual(conflict.location, '/?auth_error=account_conflict')
        self.assertIsNone(state['user'])
        self.assertIsNone(state['pendingRegistration'])
        csrf = self.start(client)
        login = self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(login.status_code, 200)
        link = self.write('/api/auth/link/google', {'next': '/'}, client=client, csrf=login.json['csrfToken'])
        self.assertEqual(link.status_code, 200)
        linked, state = callback('provider-user-1')
        self.assertEqual(linked.location, '/')
        self.assertIsNone(state['pendingRegistration'])
        self.assertEqual(state['user']['id'], local_id)
        _, again = callback('provider-user-1')
        self.assertEqual(again['user']['id'], local_id)
        _, pending = callback('provider-user-2', email='other@example.com')
        self.assertIsNone(pending['user'] if pending['user'] and pending['user']['email'] == 'other@example.com' else None)
        self.assertEqual(pending['pendingRegistration']['email'], 'other@example.com')
        csrf = pending['csrfToken']
        second = self.write('/api/auth/register', {'email': 'other@example.com', 'name': '다른 회원',
            'fullName': '다른 이름', 'password': 'correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(second.status_code, 201, second.json)
        self.assertNotEqual(second.json['user']['id'], local_id)
        failed, _ = callback('unverified', verified=False)
        self.assertEqual(failed.location, '/?auth_error=failed')
        with closing(sqlite3.connect(self.config['DATABASE'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 2)

    def test_explicit_link_preserves_legacy_comment_and_requires_both_proofs(self):
        local_id = self.signup().json['user']['id']
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            for shell_id, provider, subject in [('google-shell', 'google', 'google-old'), ('github-shell', 'github', '77')]:
                connection.execute('INSERT INTO users(id,email,password_hash,display_name,created_at) VALUES(?,NULL,NULL,?,?)',
                                   (shell_id, provider + ' 이전 계정', int(time.time())))
                connection.execute('INSERT INTO identities VALUES(?,?,?,?)', (provider, subject, shell_id, 'member@example.com'))
            connection.execute('INSERT INTO comments(page,user_id,body,created_at,updated_at) VALUES(?,?,?,?,?)',
                               ('/', 'google-shell', '기존 소셜 댓글', 1, 1))
            connection.execute('UPDATE users SET email_verified_at=NULL,registration_completed_at=NULL WHERE id=?', (local_id,))
            connection.commit()
        app = create_app({**self.config, 'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret',
                          'GITHUB_CLIENT_ID': 'test-id', 'GITHUB_CLIENT_SECRET': 'test-secret',
                          'ADMIN_USER_IDS': 'google-shell,github-shell'})
        client = app.test_client()
        csrf = self.start(client)
        login = self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get('/auth/google?link=1', base_url='https://test.example').location, '/?auth_error=reauth_required')
        self.assertEqual(self.write('/api/auth/link/google', {'next': '/'}, client=client, csrf=login.json['csrfToken']).status_code, 200)
        google = app.extensions['authlib.integrations.flask_client'].create_client('google')
        with patch.object(google, 'authorize_redirect', return_value='started'):
            self.assertEqual(client.get('/auth/google?link=1', base_url='https://test.example').status_code, 200)
        with patch.object(google, 'authorize_access_token', return_value={'userinfo': {
            'sub': 'google-old', 'email': 'member@example.com', 'email_verified': True, 'name': 'Google 회원'}}):
            self.assertEqual(client.get('/auth/google/callback', base_url='https://test.example').location, '/')
        pending = client.get('/api/session', base_url='https://test.example').json
        self.assertEqual(pending['pendingRegistration']['email'], 'member@example.com')
        completed = self.write('/api/auth/register', {'email': 'member@example.com', 'name': '통합 회원',
            'fullName': '테스트 이름', 'password': 'new correct horse battery staple'}, client=client, csrf=pending['csrfToken'])
        self.assertEqual(completed.status_code, 201, completed.json)
        self.assertEqual(completed.json['user']['id'], local_id)
        self.assertFalse(completed.json['user']['isAdmin'])
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT user_id FROM comments WHERE body=?', ('기존 소셜 댓글',)).fetchone()[0], local_id)
            self.assertEqual(connection.execute('SELECT user_id FROM identities WHERE provider=?', ('google',)).fetchone()[0], local_id)
            self.assertIsNotNone(connection.execute('SELECT id FROM users WHERE id=?', ('google-shell',)).fetchone())
        self.assertEqual(self.write('/api/auth/link/github', {'next': '/'}, client=client, csrf=completed.json['csrfToken']).status_code, 200)
        github = app.extensions['authlib.integrations.flask_client'].create_client('github')
        user = Mock(); user.json.return_value = {'id': 77, 'login': 'old-github'}
        emails = Mock(); emails.json.return_value = [{'email': 'member@example.com', 'primary': True, 'verified': True}]
        with patch.object(github, 'authorize_access_token', return_value={'access_token': 'test-token'}), \
             patch.object(github, 'get', side_effect=[user, emails]):
            self.assertEqual(client.get('/auth/github/callback', base_url='https://test.example').location, '/')
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT user_id FROM identities WHERE provider=?', ('github',)).fetchone()[0], local_id)
        new_admin = create_app({**self.config, 'ADMIN_USER_IDS': local_id})
        admin_client = new_admin.test_client()
        admin_csrf = self.start(admin_client)
        result = self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'new correct horse battery staple'},
                            client=admin_client, csrf=admin_csrf)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(admin_client.get('/api/admin/overview', base_url='https://test.example').status_code, 200)

    def test_explicit_link_refuses_legacy_identity_with_resources(self):
        local_id = self.signup().json['user']['id']
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            connection.execute('INSERT INTO users(id,email,password_hash,display_name,created_at) VALUES(?,NULL,NULL,?,?)',
                               ('busy-shell', '이전 계정', int(time.time())))
            connection.execute('INSERT INTO identities VALUES(?,?,?,?)', ('google', 'busy-subject', 'busy-shell', 'member@example.com'))
            connection.execute('INSERT INTO api_keys(id,user_id,name,token_hash,prefix,scopes,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                               ('busy-key', 'busy-shell', '이전 키', 'hash', 'prefix', '[]', 1, 9999999999))
            connection.commit()
        app = create_app({**self.config, 'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'})
        client = app.test_client()
        csrf = self.start(client)
        login = self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'correct horse battery staple'}, client=client, csrf=csrf)
        self.assertEqual(self.write('/api/auth/link/google', {'next': '/'}, client=client, csrf=login.json['csrfToken']).status_code, 200)
        provider = app.extensions['authlib.integrations.flask_client'].create_client('google')
        with patch.object(provider, 'authorize_access_token', return_value={'userinfo': {
            'sub': 'busy-subject', 'email': 'member@example.com', 'email_verified': True, 'name': '이전 계정'}}):
            self.assertEqual(client.get('/auth/google/callback', base_url='https://test.example').location, '/?auth_error=link_conflict')
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            self.assertEqual(connection.execute('SELECT user_id FROM identities WHERE subject=?', ('busy-subject',)).fetchone()[0], 'busy-shell')
            self.assertEqual(connection.execute('SELECT count(*) FROM users').fetchone()[0], 2)

    def test_rate_limit_uses_only_trusted_local_proxy_addresses(self):
        def attempts(trust_proxy, remote_addr):
            app = create_app({**self.config, 'TRUST_PROXY': trust_proxy})
            client = app.test_client()
            csrf = self.start(client)
            counter = 0
            def attempt(forwarded):
                nonlocal counter
                counter += 1
                return client.post('/api/auth/email/start', base_url='https://test.example', json={'email': f'person{counter}@example.com'},
                    environ_overrides={'REMOTE_ADDR': remote_addr}, headers={
                    'Origin': 'https://test.example', 'X-CSRF-Token': csrf, 'X-Forwarded-For': forwarded}).status_code
            return attempt
        local = attempts(True, '127.0.0.1')
        for _ in range(5):
            self.assertEqual(local('198.51.100.1'), 202)
        self.assertEqual(local('198.51.100.1'), 429)
        self.assertEqual(local('198.51.100.2'), 202)
        external = attempts(True, '203.0.113.1')
        for i in range(5):
            self.assertEqual(external(f'192.0.2.{i}'), 202)
        self.assertEqual(external('192.0.2.99'), 429)

    def test_aliases_redirect_only_reads_to_the_fixed_canonical_origin(self):
        client = create_app({**self.config, 'ALIAS_HOSTS': 'www.test.example,old.test.example'}).test_client()
        response = client.get('/guide.html?next=https://evil.example', base_url='https://www.test.example')
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.location, 'https://test.example/guide.html?next=https://evil.example')
        self.assertEqual(client.post('/api/auth/register', json={}, base_url='https://old.test.example').status_code, 403)
        self.assertEqual(client.get('/api/health', base_url='https://unknown.example').status_code, 400)


if __name__ == '__main__':
    unittest.main()
