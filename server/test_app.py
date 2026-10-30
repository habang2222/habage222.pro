import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import create_app


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
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.csrf = self.start(self.client)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, client):
        res = client.get('/api/session', base_url='https://test.example')
        self.assertEqual(res.status_code, 200)
        return res.json['csrfToken']

    def write(self, path, data, client=None, csrf=None, method='POST'):
        return (client or self.client).open(path, method=method, json=data,
            base_url='https://test.example', headers={'Origin': 'https://test.example',
            'X-CSRF-Token': self.csrf if csrf is None else csrf})

    def signup(self, email='member@example.com', name='테스트 회원', client=None, csrf=None):
        res = self.write('/api/auth/register', {'email': email, 'name': name,
            'password': 'correct horse battery staple'}, client=client, csrf=csrf)
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
        for name, email, password in [('a', 'a@example.com', 'a' * 12), ('valid', 'bad', 'a' * 12), ('valid', 'a@example.com', 'short')]:
            self.assertEqual(self.write('/api/auth/register', {'name': name, 'email': email, 'password': password}).status_code, 400)
        self.signup()
        self.assertEqual(self.write('/api/auth/register', {'name': '회원', 'email': 'MEMBER@example.com', 'password': 'a' * 12}).status_code, 409)
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
            self.assertIn(b'/community.js?v=1', res.data)
            self.assertIn(b'/community.css?v=1', res.data)
            res.close()
        res = self.client.get('/community.js', base_url='https://test.example')
        self.assertNotIn(b'innerHTML', res.data)
        self.assertIn("script-src 'self'", res.headers['Content-Security-Policy'])
        self.assertEqual(res.headers['X-Content-Type-Options'], 'nosniff')
        res.close()

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
        def callback(subject, verified=True):
            # Mock only the provider boundary; state/PKCE failure has a separate real-library test.
            info = dict(sub=subject, email='member@example.com', email_verified=verified, name='소셜 회원')
            with patch.object(provider, 'authorize_access_token', return_value={'userinfo': info}):
                response = client.get('/auth/google/callback', base_url='https://test.example')
            return response, client.get('/api/session', base_url='https://test.example').json['user']
        _, first = callback('provider-user-1')
        self.assertNotEqual(first['id'], local_id)
        _, again = callback('provider-user-1')
        self.assertEqual(first['id'], again['id'])
        _, second = callback('provider-user-2')
        self.assertNotEqual(first['id'], second['id'])
        failed, _ = callback('unverified', False)
        self.assertEqual(failed.location, '/?auth_error=failed')
        with closing(sqlite3.connect(self.config['DATABASE'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 3)

    def test_rate_limit_uses_only_trusted_local_proxy_addresses(self):
        def attempts(trust_proxy, remote_addr):
            app = create_app({**self.config, 'TRUST_PROXY': trust_proxy})
            client = app.test_client()
            csrf = self.start(client)
            def attempt(forwarded):
                return client.post('/api/auth/register', base_url='https://test.example', json={},
                    environ_overrides={'REMOTE_ADDR': remote_addr}, headers={
                    'Origin': 'https://test.example', 'X-CSRF-Token': csrf, 'X-Forwarded-For': forwarded}).status_code
            return attempt
        local = attempts(True, '127.0.0.1')
        for _ in range(5):
            self.assertEqual(local('198.51.100.1'), 400)
        self.assertEqual(local('198.51.100.1'), 429)
        self.assertEqual(local('198.51.100.2'), 400)
        external = attempts(True, '203.0.113.1')
        for i in range(5):
            self.assertEqual(external(f'192.0.2.{i}'), 400)
        self.assertEqual(external('192.0.2.99'), 429)


if __name__ == '__main__':
    unittest.main()
