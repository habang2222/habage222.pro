import base64
from contextlib import closing
import json
import sqlite3
import struct
import unittest
from unittest.mock import patch

import test_app as fixtures


def example_key():
    kind = b'ssh-ed25519'
    raw = struct.pack('>I', len(kind)) + kind + struct.pack('>I', 32) + bytes(range(32))
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


class HostDesktopTests(unittest.TestCase):
    setUp = fixtures.CommunityTests.setUp
    tearDown = fixtures.CommunityTests.tearDown
    start = fixtures.CommunityTests.start
    write = fixtures.CommunityTests.write
    verify_address = fixtures.CommunityTests.verify_address
    signup = fixtures.CommunityTests.signup

    def rows(self, sql, args=()):
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            return connection.execute(sql, args).fetchall()

    def make_admin(self, user_id):
        self.app = __import__('app').create_app({**self.config, 'ADMIN_USER_IDS': user_id})
        self.client = self.app.test_client()
        self.csrf = self.start(self.client)
        login = self.write('/api/auth/login', {'email': 'member@example.com',
                                                'password': 'correct horse battery staple'})
        self.assertEqual(login.status_code, 200)
        self.csrf = login.json['csrfToken']

    def request_access(self, password='separate remote password 123'):
        with patch('host_desktop.hash_desktop_password', return_value='$6$salt$fixture-hash') as hashed:
            response = self.write('/api/host-desktop', {'publicKey': example_key(),
                                                        'desktopPassword': password})
        return response, hashed

    def test_only_complete_members_can_request_and_secrets_are_not_returned(self):
        self.assertEqual(self.client.get('/api/host-desktop', base_url='https://test.example').status_code, 401)
        self.assertEqual(self.write('/api/host-desktop', {'publicKey': example_key(),
                                                          'desktopPassword': 'separate remote password 123'}).status_code, 401)
        incomplete = self.write('/api/auth/register', {'email': 'member@example.com',
                'name': '테스트 회원', 'password': 'correct horse battery staple'})
        self.assertNotEqual(incomplete.status_code, 201)
        self.signup()
        reused, hashed = self.request_access('correct horse battery staple')
        self.assertEqual(reused.status_code, 400)
        hashed.assert_not_called()
        response, hashed = self.request_access()
        self.assertEqual(response.status_code, 201, response.json)
        hashed.assert_called_once_with('separate remote password 123')
        self.assertEqual(response.json['request']['status'], 'pending')
        stored = self.rows('SELECT linux_user,public_key,password_hash,status FROM host_desktop_requests')[0]
        self.assertTrue(stored[0].startswith('hbdesk_'))
        self.assertEqual(stored[1], example_key())
        self.assertEqual(stored[2], '$6$salt$fixture-hash')
        self.assertEqual(stored[3], 'pending')
        for result in (response.json, self.client.get('/api/host-desktop', base_url='https://test.example').json):
            body = json.dumps(result)
            self.assertNotIn('separate remote password', body)
            self.assertNotIn('$6$', body)
            self.assertNotIn('ssh-ed25519', body)
            self.assertNotIn('public_key', body)

    def test_admin_approval_is_separate_from_rental_approval_and_revocable(self):
        admin_id = self.signup().json['user']['id']
        member = self.app.test_client()
        member_csrf = self.start(member)
        target_id = self.signup(email='other@example.com', client=member, csrf=member_csrf).json['user']['id']
        with patch('host_desktop.hash_desktop_password', return_value='$6$salt$fixture-hash'):
            request = self.write('/api/host-desktop', {'publicKey': example_key(),
                'desktopPassword': 'different remote password 123'}, client=member,
                csrf=self.start(member))
        self.assertEqual(request.status_code, 201)
        self.assertEqual(self.client.get('/api/admin/host-desktops', base_url='https://test.example').status_code, 403)
        self.make_admin(admin_id)
        data = self.client.get('/api/admin/host-desktops', base_url='https://test.example').json
        self.assertEqual(data['requests'][0]['userId'], target_id)
        self.assertNotIn('password_hash', json.dumps(data))
        self.assertNotIn('public_key', json.dumps(data))
        approved = self.write(f'/api/admin/host-desktops/{target_id}/review', {'decision': 'approve'})
        self.assertEqual(approved.status_code, 200, approved.json)
        self.assertEqual(self.rows('SELECT status FROM host_desktop_requests')[0][0], 'approved')
        self.assertFalse(self.rows('SELECT * FROM rental_permissions WHERE user_id=?', (target_id,)))
        revoked = self.write(f'/api/admin/host-desktops/{target_id}/review', {'decision': 'revoke'})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.rows('SELECT status FROM host_desktop_requests')[0][0], 'revoked')

    def test_unverified_member_cannot_be_approved(self):
        admin_id = self.signup().json['user']['id']
        member = self.app.test_client()
        member_csrf = self.start(member)
        target_id = self.signup(email='other@example.com', client=member, csrf=member_csrf).json['user']['id']
        with patch('host_desktop.hash_desktop_password', return_value='$6$salt$fixture-hash'):
            response = self.write('/api/host-desktop', {'publicKey': example_key(),
                'desktopPassword': 'different remote password 123'}, client=member,
                csrf=self.start(member))
        self.assertEqual(response.status_code, 201)
        with closing(sqlite3.connect(self.config['DATABASE'])) as connection:
            connection.execute('UPDATE users SET email_verified_at=NULL WHERE id=?', (target_id,))
            connection.commit()
        self.make_admin(admin_id)
        denied = self.write(f'/api/admin/host-desktops/{target_id}/review', {'decision': 'approve'})
        self.assertEqual(denied.status_code, 409)

    def test_member_can_revoke_and_reapply_without_keeping_old_access(self):
        self.signup()
        first, _ = self.request_access()
        self.assertEqual(first.status_code, 201)
        cancelled = self.write('/api/host-desktop', {}, method='DELETE')
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self.rows('SELECT status FROM host_desktop_requests')[0][0], 'revoked')
        second, _ = self.request_access('new remote password 456')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.rows('SELECT status FROM host_desktop_requests')[0][0], 'pending')


if __name__ == '__main__':
    unittest.main()
