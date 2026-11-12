import base64
from contextlib import closing
import hashlib
import json
import os
import sqlite3
import struct
import time
import unittest
from unittest.mock import patch

import test_app as fixtures
from rental_worker import Runtime, Worker
from rental_common import validate_public_key


def example_key():
    kind = b'ssh-ed25519'
    raw = struct.pack('>I', len(kind)) + kind + struct.pack('>I', 32) + bytes(range(32))
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


class RuntimeFake:
    def __init__(self):
        self.calls = []

    def operate(self, action, row):
        self.calls.append((action, row['id']))
        return 'SHA256:test-fingerprint' if action in ('create', 'start', 'restart') else None


class PortalTests(unittest.TestCase):
    setUp = fixtures.CommunityTests.setUp
    tearDown = fixtures.CommunityTests.tearDown
    start = fixtures.CommunityTests.start
    write = fixtures.CommunityTests.write
    verify_address = fixtures.CommunityTests.verify_address
    signup = fixtures.CommunityTests.signup
    def add_member(self):
        return self.signup().json['user']['id']

    def rows(self, sql, args=()):
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            result = connection.execute(sql, args).fetchall()
            connection.commit()
            return result

    def make_admin(self, user_id):
        # The app captures the configured set during startup.
        self.app = __import__('app').create_app({**self.config, 'ADMIN_USER_IDS': user_id})
        client = self.app.test_client()
        self.csrf = self.start(client)
        self.client = client
        response = self.write('/api/auth/login', {'email': 'member@example.com', 'password': 'correct horse battery staple'})
        self.csrf = response.json['csrfToken']

    def ready(self):
        self.rows("INSERT OR REPLACE INTO rental_runtime VALUES(1,?,1,'ready')", (int(time.time()),))

    def test_home_loads_current_hbcode_list_without_stale_script_cache(self):
        from pathlib import Path
        root = Path(self.config['SITE_ROOT'])
        links_digest = hashlib.sha256((root / 'links.js').read_bytes()).hexdigest()[:12]
        home_digest = hashlib.sha256((root / 'home.js').read_bytes()).hexdigest()[:12]
        home = self.client.get('/', base_url='https://test.example')
        self.assertIn(f'links.js?v={links_digest}'.encode(), home.data)
        self.assertIn(f'home.js?v={home_digest}'.encode(), home.data)
        self.assertEqual(home.headers['Cache-Control'], 'no-cache, max-age=0, must-revalidate')
        home.close()
        links = self.client.get(f'/links.js?v={links_digest}', base_url='https://test.example')
        self.assertIn(b'title: "HBcode"', links.data)
        self.assertEqual(links.headers['Cache-Control'], 'no-cache, max-age=0, must-revalidate')
        links.close()
        script = self.client.get(f'/home.js?v={home_digest}', base_url='https://test.example')
        self.assertIn(b'downloadOnly', script.data)
        self.assertEqual(script.headers['Cache-Control'], 'no-cache, max-age=0, must-revalidate')
        script.close()

        site = Path(self.temp.name) / 'cache-site'
        site.mkdir()
        for filename in ('index.html', 'links.js', 'home.js'):
            (site / filename).write_bytes((root / filename).read_bytes())
        copy_app = __import__('app').create_app({**self.config, 'SITE_ROOT': str(site)})
        copy_client = copy_app.test_client()
        before = copy_client.get('/', base_url='https://test.example')
        old_url = f'links.js?v={links_digest}'.encode()
        self.assertIn(old_url, before.data)
        before.close()
        (site / 'links.js').write_bytes((site / 'links.js').read_bytes() + b'\n// new link\n')
        updated_digest = hashlib.sha256((site / 'links.js').read_bytes()).hexdigest()[:12]
        after = copy_client.get('/', base_url='https://test.example')
        self.assertIn(f'links.js?v={updated_digest}'.encode(), after.data)
        self.assertNotIn(old_url, after.data)
        after.close()

    def rental(self):
        return self.write('/api/rentals', {'name': '개발 서버', 'publicKey': example_key()})

    def test_kali_rental_option_preserves_existing_workspace_plan(self):
        owner = self.add_member()
        self.make_admin(owner)
        self.ready()
        services = self.client.get('/api/services', base_url='https://test.example').json
        self.assertEqual({plan['id'] for plan in services['plans']}, {'workspace', 'kali-workspace'})
        self.assertEqual(next(plan['memoryMb'] for plan in services['plans'] if plan['id'] == 'kali-workspace'), 512)
        rejected = self.write('/api/rentals', {'name': '잘못된 유형', 'plan': 'unknown', 'publicKey': example_key()})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(self.rows('SELECT count(*) FROM rentals')[0][0], 0)
        result = self.write('/api/rentals', {'name': 'Kali 작업 공간', 'plan': 'kali-workspace',
                                             'publicKey': example_key()})
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json['rental']['plan'], 'kali-workspace')
        self.assertEqual(self.rows('SELECT plan FROM rentals')[0][0], 'kali-workspace')

    def test_kali_runtime_uses_its_own_image_and_memory_limit(self):
        from pathlib import Path
        with patch.dict(os.environ, {'RENTAL_STATE': str(Path(self.temp.name) / 'rental-state')}):
            runtime = Runtime()
        runtime.images = {'workspace': 'sha256:debian', 'kali-workspace': 'sha256:kali'}
        row = {'id': 'a' * 32, 'plan': 'kali-workspace', 'ssh_port': 23000,
               'public_key': example_key()}
        (runtime.state / (row['id'] + '.hostkey')).write_text('test', encoding='ascii')
        details = {'HostConfig': {'Memory': 512 * 1024 * 1024, 'PidsLimit': 64,
                                  'ReadonlyRootfs': True}, 'State': {'Running': True}}
        inspections = iter((None, details))
        runtime.inspect = lambda _row: next(inspections)
        commands = []
        def fake_command(*args, **_kwargs):
            commands.append(args)
            return '[]' if args[:2] == ('ps', '-a') else ''
        runtime.command = fake_command
        runtime.wait_for_ssh = lambda _row: 'SHA256:test'
        self.assertEqual(runtime.create(row), 'SHA256:test')
        create = next(args for args in commands if args[0] == 'create')
        self.assertIn('sha256:kali', create)
        self.assertNotIn('sha256:debian', create)
        self.assertEqual(create[create.index('--memory') + 1], '512m')
        self.assertIn('pro.habang.plan=kali-workspace', create)

    def test_keys_only_reveal_secret_once_and_revoke(self):
        owner = self.add_member()
        response = self.write('/api/keys', {'name': '개발 도구', 'program': 'lecture-alarm', 'days': 7})
        self.assertEqual(response.status_code, 201)
        token = response.json['secret']
        key_id = response.json['key']['id']
        stored = self.rows('SELECT token_hash,prefix FROM api_keys WHERE id=?', (key_id,))[0]
        self.assertEqual(stored[0], hashlib.sha256(token.encode()).hexdigest())
        listing = self.client.get('/api/keys', base_url='https://test.example').json
        self.assertNotIn(token, json.dumps(listing))
        headers = {'Authorization': 'Bearer ' + token}
        profile = self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example')
        self.assertEqual(profile.json['program']['id'], 'lecture-alarm')
        self.assertEqual(profile.headers['Cache-Control'], 'no-store')
        self.assertNotIn('email', profile.json['program'])
        self.write('/api/keys/' + key_id, {}, method='DELETE')
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 401)

    def test_hbcode_download_login_scope_and_integrity(self):
        from pathlib import Path
        site = Path(self.temp.name) / 'site'
        (site / 'downloads').mkdir(parents=True)
        filename = 'HBcode-0.3.0-windows-x64.zip'
        payload = b'PK\x03\x04isolated-hbcode-fixture'
        (site / 'downloads' / filename).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (site / 'downloads/manifest.json').write_text(json.dumps({'sha256': {filename: digest}}), encoding='utf-8')
        self.app = __import__('app').create_app({**self.config, 'SITE_ROOT': str(site)})
        self.client = self.app.test_client()
        self.csrf = self.start(self.client)
        path = '/downloads/' + filename
        guest = self.client.get(path, base_url='https://test.example')
        self.assertEqual(guest.status_code, 302)
        self.assertIn('download=hbcode', guest.location)
        self.add_member()
        member = self.client.get(path, base_url='https://test.example')
        self.assertEqual(member.status_code, 200)
        self.assertEqual(member.data, payload)
        member.close()
        program = next(row for row in self.client.get('/api/programs', base_url='https://test.example').json['programs'] if row['id'] == 'hbcode')
        self.assertEqual(program['files'][0]['sha256'], digest)
        issued = self.write('/api/keys', {'name': 'HBcode 테스트', 'program': 'hbcode'}).json
        headers = {'Authorization': 'Bearer ' + issued['secret']}
        result = self.client.get('/api/v1/programs/hbcode/download', headers=headers, base_url='https://test.example')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, payload)
        result.close()
        self.assertEqual(self.client.get('/api/v1/programs/mglogwh/download', headers=headers, base_url='https://test.example').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/programs/hbcode/files/unknown.zip', headers=headers, base_url='https://test.example').status_code, 404)

    def test_key_scope_expiry_and_cookie_are_independent(self):
        self.add_member()
        response = self.write('/api/keys', {'name': '프로그램 전용', 'program': 'lecture-alarm', 'days': 30})
        token = response.json['secret']
        headers = {'Authorization': 'Bearer ' + token}
        self.assertEqual(self.client.get('/api/v1/programs/mglogwh', headers=headers, base_url='https://test.example').status_code, 403)
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', base_url='https://test.example').status_code, 401)
        self.rows('UPDATE api_keys SET expires_at=0')
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 401)
        self.assertEqual(self.write('/api/keys', {'name': '관리자 키', 'program': 'unknown'}).status_code, 400)

    def test_existing_key_and_download_stop_when_owner_verification_is_removed(self):
        owner = self.add_member()
        issued = self.write('/api/keys', {'name': '프로그램 키', 'program': 'lecture-alarm'}).json
        headers = {'Authorization': 'Bearer ' + issued['secret']}
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 200)
        self.rows('UPDATE users SET email_verified_at=NULL WHERE id=?', (owner,))
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm/download', headers=headers, base_url='https://test.example').status_code, 401)
        self.assertEqual(self.client.get('/api/keys', base_url='https://test.example').status_code, 403)
        self.assertEqual(self.client.get('/downloads/cu-lms-lecture-alarm-v2.2.0.zip', base_url='https://test.example').status_code, 302)
        self.assertEqual(self.write('/api/rentals', {'name': '테스트 서버', 'publicKey': example_key()}).status_code, 403)
        self.verify_address()
        restored = self.write('/api/auth/register', {'email': 'member@example.com', 'name': '테스트 회원',
            'fullName': '테스트 이름', 'password': 'new correct horse battery staple'})
        self.assertEqual(restored.status_code, 201)
        self.csrf = restored.json['csrfToken']
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', headers=headers, base_url='https://test.example').status_code, 401)
        self.assertIsNotNone(self.rows('SELECT revoked_at FROM api_keys WHERE id=?', (issued['key']['id'],))[0][0])

    def test_admin_cannot_approve_unverified_account(self):
        admin_id = self.add_member()
        member = self.app.test_client()
        member_csrf = self.start(member)
        target = self.signup(email='pending@example.com', client=member, csrf=member_csrf).json['user']['id']
        self.make_admin(admin_id)
        self.rows('UPDATE users SET registration_completed_at=NULL WHERE id=?', (target,))
        response = self.write(f'/api/admin/users/{target}/rental-access', {'approved': True})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.rows('SELECT approved FROM rental_permissions WHERE user_id=?', (target,)))

    def test_program_download_integrity_scope_and_key_ownership(self):
        owner = self.add_member()
        other = self.app.test_client()
        other_csrf = self.start(other)
        other_id = self.signup(email='other@example.com', client=other, csrf=other_csrf).json['user']['id']
        issued = self.write('/api/keys', {'name': '프로그램 다운로드', 'program': 'lecture-alarm'}).json
        headers = {'Authorization': 'Bearer ' + issued['secret']}
        result = self.client.get('/api/v1/programs/lecture-alarm/download', base_url='https://test.example', headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.data.startswith(b'PK'))
        from pathlib import Path
        expected = (Path(self.config['SITE_ROOT']) / 'downloads/cu-lms-lecture-alarm-v2.2.0.zip').read_bytes()
        self.assertEqual(hashlib.sha256(result.data).digest(), hashlib.sha256(expected).digest())
        result.close()
        wrong = self.client.get('/api/v1/programs/random-backspace/download', base_url='https://test.example', headers=headers)
        self.assertEqual(wrong.status_code, 403)
        other_csrf = self.start(other)
        self.assertEqual(self.write('/api/keys/' + issued['key']['id'], {}, client=other, csrf=other_csrf, method='DELETE').status_code, 404)

    def test_key_limit_and_rate_limit(self):
        self.add_member()
        for _ in range(5):
            response = self.write('/api/keys', {'name': '테스트 키', 'program': 'lecture-alarm'})
            self.assertEqual(response.status_code, 201)
        self.assertEqual(self.write('/api/keys', {'name': '추가 키', 'program': 'lecture-alarm'}).status_code, 409)
        headers = {'Authorization': 'Bearer ' + response.json['secret']}
        for _ in range(60):
            self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', base_url='https://test.example', headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/v1/programs/lecture-alarm', base_url='https://test.example', headers=headers).status_code, 429)

    def test_website_downloads_require_login_and_api_never_accepts_query_keys(self):
        anonymous = self.app.test_client()
        response = anonymous.get('/downloads/cu-lms-lecture-alarm-v2.2.0.zip', base_url='https://test.example')
        self.assertEqual(response.status_code, 302)
        self.add_member()
        response = self.client.get('/downloads/cu-lms-lecture-alarm-v2.2.0.zip', base_url='https://test.example')
        self.assertEqual(response.status_code, 200)
        response.close()
        issued = self.write('/api/keys', {'name': '다운로드 키', 'program': 'lecture-alarm'}).json
        response = anonymous.get('/api/v1/programs/lecture-alarm/download?key=' + issued['secret'], base_url='https://test.example')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(anonymous.get('/downloads/unknown.zip', base_url='https://test.example').status_code, 404)
        self.assertEqual(anonymous.get('/downloads/manifest.json', base_url='https://test.example').status_code, 404)
        self.assertEqual(self.rows('SELECT count(*) FROM download_events')[0][0], 1)

    def test_request_needs_approval_then_worker_creates_and_lifecycle(self):
        owner = self.add_member()
        response = self.rental()
        self.assertEqual(response.status_code, 201)
        rental_id = response.json['rental']['id']
        self.assertEqual(response.json['rental']['status'], 'pending')
        self.assertEqual(self.rows('SELECT count(*) FROM rental_jobs')[0][0], 0)
        self.assertEqual(self.rental().status_code, 409)
        self.assertEqual(self.write(f'/api/admin/rentals/{rental_id}/review', {'decision': 'approve'}).status_code, 403)
        self.make_admin(owner)
        self.ready()
        self.assertEqual(self.write(f'/api/admin/rentals/{rental_id}/review', {'decision': 'approve'}).status_code, 200)
        fake = RuntimeFake()
        worker = Worker(self.config['DATABASE'], fake)
        worker.run_once()
        result = self.client.get('/api/rentals', base_url='https://test.example').json['rentals'][0]
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['sshPort'], 23000)
        self.assertTrue(result['expires_at'])
        for action, state in [('stop', 'stopped'), ('start', 'running'), ('restart', 'running'), ('terminate', 'terminated')]:
            self.assertEqual(self.write(f'/api/rentals/{rental_id}/actions', {'action': action}).status_code, 200)
            worker.run_once()
            self.assertEqual(self.rows('SELECT status FROM rentals WHERE id=?', (rental_id,))[0][0], state)
        self.assertIsNone(self.rows('SELECT ssh_port FROM rentals WHERE id=?', (rental_id,))[0][0])
        worker.db.close()

    def test_account_approval_queues_pending_and_future_requests(self):
        owner = self.add_member()
        rental_id = self.rental().json['rental']['id']
        self.make_admin(owner)
        self.ready()
        self.assertEqual(self.write(f'/api/admin/users/{owner}/rental-access', {'approved': True}).status_code, 200)
        self.assertEqual(self.rows('SELECT status FROM rentals WHERE id=?', (rental_id,))[0][0], 'queued')
        self.rows("UPDATE rentals SET status='terminated',ssh_port=NULL")
        self.assertEqual(self.rental().json['rental']['status'], 'queued')

    def test_capacity_and_offline_runtime_never_create_fake_running_server(self):
        owner = self.add_member()
        self.make_admin(owner)
        self.assertEqual(self.rental().status_code, 503)
        self.assertEqual(self.rows('SELECT count(*) FROM rentals')[0][0], 0)
        self.ready()
        self.assertEqual(self.rental().status_code, 201)
        self.rows("UPDATE rentals SET status='running'")
        self.assertEqual(self.rental().status_code, 409)

    def test_rental_key_validation_and_admin_scope(self):
        self.add_member()
        for bad in ['-----BEGIN PRIVATE KEY-----', 'command="bad" ' + example_key(), 'ssh-ed25519 AAAA', example_key() + '\n' + example_key()]:
            self.assertEqual(self.write('/api/rentals', {'name': '테스트 서버', 'publicKey': bad}).status_code, 400)
        self.assertEqual(validate_public_key(example_key() + ' pc-name'), example_key())
        self.assertEqual(self.client.get('/api/admin/overview', base_url='https://test.example').status_code, 403)
        response = self.rental()
        rental_id = response.json['rental']['id']
        other = self.app.test_client()
        csrf = self.start(other)
        res = self.signup(email='other@example.com', client=other, csrf=csrf)
        self.assertEqual(self.write(f'/api/rentals/{rental_id}/actions', {'action': 'cancel'}, client=other, csrf=res.json['csrfToken']).status_code, 404)

    def test_global_capacity_blocks_third_approval_atomically(self):
        owner = self.add_member()
        self.make_admin(owner)
        self.ready()
        self.assertEqual(self.rental().status_code, 201)
        for number in (2, 3):
            other = self.app.test_client()
            csrf = self.start(other)
            member = self.signup(email=f'member{number}@example.com', client=other, csrf=csrf)
            request = self.write('/api/rentals', {'name': '테스트 서버', 'publicKey': example_key()}, client=other, csrf=member.json['csrfToken'])
            self.assertEqual(request.status_code, 201)
            user_id = member.json['user']['id']
            decision = self.write(f'/api/admin/users/{user_id}/rental-access', {'approved': True})
            self.assertEqual(decision.status_code, 200 if number == 2 else 409)
            if number == 3:
                self.assertEqual(self.rows('SELECT status FROM rentals WHERE id=?', (request.json['rental']['id'],))[0][0], 'pending')
                self.assertFalse(self.rows('SELECT approved FROM rental_permissions WHERE user_id=?', (user_id,)))
        self.assertEqual(self.rows("SELECT count(*) FROM rentals WHERE status='queued'")[0][0], 2)

    def test_worker_expiry_and_crash_recovery_do_not_duplicate_jobs(self):
        owner = self.add_member()
        self.make_admin(owner)
        self.ready()
        rental_id = self.rental().json['rental']['id']
        fake = RuntimeFake()
        worker = Worker(self.config['DATABASE'], fake)
        claimed = worker.claim()
        self.assertEqual(claimed[1]['status'], 'provisioning')
        self.rows('UPDATE rental_jobs SET lease_until=0')
        worker.run_once()
        self.assertEqual(len(fake.calls), 1)
        self.rows('UPDATE rentals SET expires_at=0 WHERE id=?', (rental_id,))
        worker.run_once()
        self.assertEqual(fake.calls[-1][0], 'expire')
        self.assertEqual(self.rows('SELECT status FROM rentals WHERE id=?', (rental_id,))[0][0], 'expired')
        worker.run_once()
        self.assertEqual(len(fake.calls), 2)
        worker.db.close()


if __name__ == '__main__':
    unittest.main()
