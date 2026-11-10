from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from backup_database import backup, check_integrity, verify_restore


class BackupTests(unittest.TestCase):
    def test_online_backup_and_restore_preserve_wal_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / 'live.sqlite3'
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('PRAGMA journal_mode=WAL')
                for name in ('users', 'comments', 'rentals'):
                    connection.execute(f'CREATE TABLE {name}(id TEXT)')
                connection.execute("INSERT INTO users VALUES('member')")
                connection.commit()
                connection.execute('PRAGMA wal_checkpoint(PASSIVE)')
                connection.execute("INSERT INTO comments VALUES('comment')")
                connection.commit()
                snapshot, counts = backup(database, root / 'backups')
                self.assertEqual(counts, {'comments': 1, 'rentals': 0, 'users': 1})
                self.assertEqual(check_integrity(snapshot), counts)
                self.assertEqual(verify_restore(snapshot, root / 'backups'), counts)

    def test_missing_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                check_integrity(Path(folder) / 'missing.sqlite3')


if __name__ == '__main__':
    unittest.main()
