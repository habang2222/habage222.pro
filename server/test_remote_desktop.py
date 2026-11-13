from contextlib import closing
import hashlib
import sqlite3
import unittest

from remote_desktop import (Instructions, acquire_lease, authorized_user,
                            browser_input, instruction, rdp_handshake)
from test_host_desktop import HostDesktopTests


class ProtocolTests(unittest.TestCase):
    def test_fragmented_lengths_and_embedded_delimiters(self):
        encoded = instruction('test', '한글,.;😀') + instruction('sync', 12)
        parser = Instructions()
        values = []
        for char in encoded:
            values.extend(parser.feed(char))
        self.assertEqual(values, [['test','한글,.;😀'],['sync','12']])

    def test_handshake_cannot_be_injected_through_input(self):
        for name in ('select','connect','clipboard','file','pipe','get','put','blob','argv'):
            with self.assertRaises(ValueError):
                browser_input(instruction(name, '127.0.0.1'), Instructions())
        self.assertEqual(browser_input(instruction('key', 65, 1), Instructions()), [['key','65','1']])
        for values in [('key',65,7),('key',2**40,1),('key',65),('mouse',0,0,1024),('sync',-1),('nop','extra')]:
            with self.assertRaises(ValueError):
                browser_input(instruction(*values), Instructions())
        for data in ('-1.x;', '999999.x;', '1.x!', 'x.x;', '1.' + 'A' * 32768):
            with self.assertRaises(ValueError):
                Instructions().feed(data)

    def test_rdp_target_and_username_are_fixed_and_redirections_disabled(self):
        class Stream:
            sent = []
            def sendall(self, value): self.sent.append(value)
            def recv(self, size):
                return instruction('args', 'VERSION_1_5_0','hostname','port','username','password',
                    'enable-drive','disable-copy','disable-paste','security').encode()
        stream = Stream()
        rdp_handshake(stream,'hbdesk_' + 'a'*16,'not-stored',1280,720)
        packets = Instructions().feed(b''.join(stream.sent).decode())
        self.assertEqual(packets[0], ['select','rdp'])
        self.assertEqual(packets[-1], ['connect','VERSION_1_5_0','127.0.0.1','3389',
                        'hbdesk_' + 'a'*16,'not-stored','false','true','true','tls'])


class RemoteAuthorizationTests(HostDesktopTests):
    def test_session_expiry_revocation_and_target_ownership(self):
        user_id = self.signup().json['user']['id']
        self.request_access()
        token = self.client.get_cookie('__Host-habang_sid', domain='test.example').value
        digest = hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(self.config['DATABASE'])) as db:
            db.row_factory = sqlite3.Row
            self.assertIsNone(authorized_user(db,user_id,digest,set()))
            db.execute("UPDATE host_desktop_requests SET status='ready'"); db.commit()
            self.assertEqual(authorized_user(db,user_id,digest,set()),'hbdesk_'+user_id[:16])
            self.assertIsNone(authorized_user(db,'b'*32,digest,set()))
            db.execute("UPDATE host_desktop_requests SET linux_user='habang222'"); db.commit()
            self.assertIsNone(authorized_user(db,user_id,digest,set()))
            self.assertEqual(authorized_user(db,user_id,digest,{user_id}), 'habang222')
            db.execute('DELETE FROM sessions'); db.commit()
            self.assertIsNone(authorized_user(db,user_id,digest,{user_id}))

    def test_origin_must_match_before_websocket_upgrade(self):
        self.assertEqual(self.client.get('/api/remote/host',base_url='https://test.example').status_code,401)
        self.signup()
        response = self.client.get('/api/remote/host',base_url='https://test.example',headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code,403)
        response = self.client.get('/api/remote/host',base_url='https://test.example')
        self.assertEqual(response.status_code,403)

    def test_connection_lease_is_shared_and_stale_lease_expires(self):
        user_id = self.signup().json['user']['id']
        with closing(sqlite3.connect(self.config['DATABASE'])) as first, closing(sqlite3.connect(self.config['DATABASE'])) as second:
            self.assertTrue(acquire_lease(first,user_id,'first',100))
            self.assertFalse(acquire_lease(second,user_id,'second',101))
            self.assertTrue(acquire_lease(second,user_id,'second',121))

    def test_browser_only_registration_needs_no_ssh_key(self):
        from unittest.mock import patch
        self.signup()
        with patch('host_desktop.hash_desktop_password',return_value='$6$salt$fixture-hash'):
            response = self.write('/api/host-desktop',{'desktopPassword':'different remote password 456'})
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.rows('SELECT public_key FROM host_desktop_requests')[0][0], '')


if __name__ == '__main__': unittest.main()
