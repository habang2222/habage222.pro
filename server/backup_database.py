"""Consistent SQLite snapshots, restore verification, and startup integrity gate."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def open_readonly(path):
    if not path.is_file():
        raise FileNotFoundError(f'Database missing: {path}')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)
    connection.execute('PRAGMA query_only=ON')
    return connection


def check_integrity(path):
    with closing(open_readonly(path)) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError(f'Database integrity check failed: {path}')
        # A valid but empty/new SQLite file must not silently replace live data.
        required = {'users', 'comments', 'rentals'}
        found = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= found:
            raise RuntimeError(f'Database schema missing: {path}')
        return {name: connection.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                for name in sorted(required)}


def verify_restore(snapshot, backup_dir):
    with tempfile.TemporaryDirectory(prefix='.restore-check-', dir=backup_dir) as scratch:
        restored = Path(scratch) / 'restored.sqlite3'
        shutil.copyfile(snapshot, restored)
        return check_integrity(restored)


def backup(database, backup_dir, keep_days=30):
    check_integrity(database)
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = backup_dir / f'community-{stamp}.sqlite3'
    if destination.exists():
        raise FileExistsError(destination)
    descriptor, temporary = tempfile.mkstemp(prefix='.backup-', suffix='.sqlite3', dir=backup_dir)
    os.close(descriptor)
    os.chmod(temporary, 0o600)
    try:
        with closing(open_readonly(database)) as source, closing(sqlite3.connect(temporary, timeout=30)) as target:
            source.backup(target)
        counts = check_integrity(Path(temporary))
        with open(temporary, 'r+b') as file:
            os.fsync(file.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        if os.name != 'nt':
            directory_fd = os.open(backup_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        if verify_restore(destination, backup_dir) != counts:
            raise RuntimeError('Restored snapshot does not match its source')
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        snapshots = sorted(backup_dir.glob('community-????????T??????Z.sqlite3'), reverse=True)
        for old in snapshots[7:]:
            if datetime.fromtimestamp(old.stat().st_mtime, timezone.utc) < cutoff:
                old.unlink()
        return destination, counts
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=Path(os.environ.get('DATABASE', '/srv/files/data/community.sqlite3')))
    parser.add_argument('--backup-dir', type=Path, default=Path('/srv/files/backups/scheduled'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check-only', action='store_true')
    group.add_argument('--verify-latest', action='store_true')
    args = parser.parse_args()
    if args.check_only:
        print('Database integrity OK:', check_integrity(args.database))
    elif args.verify_latest:
        latest = max(args.backup_dir.glob('community-????????T??????Z.sqlite3'), default=None)
        if latest is None:
            raise RuntimeError('No scheduled backup found')
        print('Backup restore verified:', latest, verify_restore(latest, args.backup_dir))
    else:
        path, counts = backup(args.database, args.backup_dir)
        print('Backup and restore verified:', path, counts)
