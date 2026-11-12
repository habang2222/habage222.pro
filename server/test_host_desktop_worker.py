import base64
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from host_desktop import HOST_DESKTOP_SCHEMA
from host_desktop_worker import AccountRuntime, ProvisionError, Worker, authorized_key


def public_key():
    kind = b'ssh-ed25519'
    raw = struct.pack('>I', len(kind)) + kind + struct.pack('>I', 32) + bytes(range(32))
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


class RuntimeFake:
    def __init__(self):
        self.created = []
        self.disabled = []
    def provision(self, row): self.created.append(row['user_id'])
    def deactivate(self, row): self.disabled.append(row['user_id'])
    def is_current(self, row): return True
    def managed_accounts(self): return []


class HostWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'test.db')
        self.uid = 'a' * 32
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,email_verified_at INTEGER,registration_completed_at INTEGER)')
            db.executescript(HOST_DESKTOP_SCHEMA)
            db.execute('INSERT INTO users VALUES(?,1,1)', (self.uid,))
            db.execute('''INSERT INTO host_desktop_requests
              (user_id,linux_user,public_key,password_hash,status,requested_at,updated_at,approved_by,approved_at)
              VALUES(?,?,?,?,'approved',1,1,?,1)''',
              (self.uid, 'hbdesk_' + self.uid[:16], public_key(), '$6$12345678$' + 'A'*86, self.uid))
        self.runtime = RuntimeFake()
        self.worker = Worker(self.database, self.runtime, clock=lambda: 10)
    def tearDown(self):
        self.worker.close()
        self.temp.cleanup()
    def execute(self, sql):
        with closing(sqlite3.connect(self.database)) as db, db: db.execute(sql)
    def status(self):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT status FROM host_desktop_requests').fetchone()[0]
    def test_approval_then_revocation(self):
        self.worker.run_once()
        self.assertEqual(self.status(), 'ready')
        self.assertEqual(self.runtime.created, [self.uid])
        self.execute("UPDATE host_desktop_requests SET status='revoked'")
        self.worker.run_once()
        self.assertIn(self.uid, self.runtime.disabled)
        self.assertEqual(self.status(), 'revoked')
    def test_removed_verification_disables_ready_account(self):
        self.execute('UPDATE users SET email_verified_at=NULL')
        self.worker.run_once()
        self.assertEqual(self.runtime.created, [])
        self.assertEqual(self.runtime.disabled, [self.uid])
        self.assertEqual(self.status(), 'failed')
    def test_revocation_during_provision_never_marks_ready(self):
        def provision(row): self.execute("UPDATE host_desktop_requests SET status='revoked'")
        self.runtime.provision = provision
        self.worker.run_once()
        self.assertEqual(self.status(), 'revoked')
        self.assertIn(self.uid, self.runtime.disabled)
    def test_restricted_key_and_tampered_home_fail_closed(self):
        line = authorized_key(public_key()).decode()
        self.assertIn('restrict,port-forwarding,permitopen="127.0.0.1:3389"', line)
        system = Mock()
        system.shadow_hash.return_value = '$6$12345678$' + 'A'*86
        system.has_processes.return_value = True
        files = Mock()
        files.remove_key.side_effect = ProvisionError('tampered directory')
        runtime = AccountRuntime(system, files)
        runtime._account = Mock(return_value=SimpleNamespace(pw_name='hbdesk_' + self.uid[:16], pw_uid=1002))
        with self.assertRaises(ProvisionError): runtime.deactivate({'user_id': self.uid})
        commands = [call.args[0] for call in system.run.call_args_list]
        self.assertIn(['/usr/sbin/usermod', '--expiredate', '1', 'hbdesk_' + self.uid[:16]], commands)
        self.assertIn(['/usr/bin/pkill', '-KILL', '-u', '1002'], commands)


if __name__ == '__main__': unittest.main()
