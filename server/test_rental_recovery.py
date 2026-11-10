from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from rental_worker import Worker


SCHEMA = """
CREATE TABLE users(id TEXT PRIMARY KEY,email_verified_at INTEGER,registration_completed_at INTEGER);
CREATE TABLE rentals(id TEXT PRIMARY KEY,user_id TEXT,status TEXT,expires_at INTEGER,
                     updated_at INTEGER,last_error TEXT,ssh_port INTEGER,plan TEXT,
                     ssh_fingerprint TEXT);
CREATE TABLE rental_jobs(id TEXT PRIMARY KEY,rental_id TEXT,action TEXT,status TEXT,
                         created_at INTEGER,lease_until INTEGER,attempts INTEGER DEFAULT 0);
CREATE TABLE rental_runtime(id INTEGER PRIMARY KEY,heartbeat INTEGER,ready INTEGER,message TEXT);
"""


class RuntimeFake:
    def __init__(self, running=False, missing=False):
        self.running = running
        self.missing = missing
        self.actions = []

    def inspect(self, row):
        return None if self.missing else {'State': {'Running': self.running}}

    def operate(self, action, row):
        self.actions.append(action)
        self.running = action in ('create', 'start', 'restart')
        return 'SHA256:test' if self.running else None


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.database = str(Path(self.scratch.name) / 'test.sqlite3')
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(SCHEMA)
            connection.execute('INSERT INTO users VALUES(?,?,?)', ('owner', 1, 1))
            connection.execute("INSERT INTO rentals VALUES('rental','owner','running',NULL,0,NULL,23000,'workspace',NULL)")
            connection.commit()

    def tearDown(self):
        self.scratch.cleanup()

    def open_worker(self, runtime):
        return Worker(self.database, runtime)

    def test_stopped_container_is_restarted_once_after_reboot(self):
        runtime = RuntimeFake(running=False)
        worker = self.open_worker(runtime)
        try:
            worker.recover_startup()
            worker.reconcile()
            self.assertEqual(worker.db.execute("SELECT status FROM rentals").fetchone()[0], 'starting')
            self.assertEqual(worker.db.execute("SELECT count(*) FROM rental_jobs").fetchone()[0], 1)
            worker.run_once()
            self.assertEqual(runtime.actions, ['start'])
            self.assertEqual(worker.db.execute("SELECT status FROM rentals").fetchone()[0], 'running')
        finally:
            worker.db.close()

    def test_unverified_running_container_is_stopped(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE users SET registration_completed_at=NULL')
            connection.commit()
        runtime = RuntimeFake(running=True)
        worker = self.open_worker(runtime)
        try:
            worker.reconcile()
            worker.run_once()
            self.assertEqual(runtime.actions, ['stop'])
            self.assertEqual(worker.db.execute("SELECT status FROM rentals").fetchone()[0], 'stopped')
        finally:
            worker.db.close()

    def test_unverified_create_is_denied_even_if_job_queued(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('UPDATE users SET email_verified_at=NULL')
            connection.execute("UPDATE rentals SET status='queued'")
            connection.execute("INSERT INTO rental_jobs VALUES('job','rental','create','queued',?,NULL,0)", (int(time.time()),))
            connection.commit()
        runtime = RuntimeFake(missing=True)
        worker = self.open_worker(runtime)
        try:
            worker.run_once()
            self.assertEqual(runtime.actions, [])
            self.assertEqual(worker.db.execute("SELECT status FROM rentals").fetchone()[0], 'failed')
        finally:
            worker.db.close()


if __name__ == '__main__':
    unittest.main()
