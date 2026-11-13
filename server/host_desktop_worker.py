"""Root-only reconciler for approved, individually isolated Kali desktop accounts.

The web process only writes requests to SQLite. It never runs account commands.
"""
import hashlib
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import time

from rental_common import valid_id, validate_public_key


LOG = logging.getLogger('habang-host-desktop')
GROUP = 'hbdesktop'
MARKER = 'habang-host-desktop'
STATUSES = {'pending', 'approved', 'ready', 'revoked', 'failed'}
LINUX_USER = re.compile(r'hbdesk_[a-f0-9]{16}\Z')
SHA512_CRYPT = re.compile(r'\$6\$(?:rounds=[0-9]{1,7}\$)?[A-Za-z0-9./]{8,16}\$[A-Za-z0-9./]{86}\Z')
XSESSION = b'exec startxfce4\n'
ERROR = '원격 데스크톱 계정을 준비하지 못했습니다. 관리자에게 문의해 주세요.'
UNVERIFIED = '계정 확인이 만료되어 원격 접속이 중지되었습니다.'


class ProvisionError(RuntimeError):
    pass


def identity(row):
    user_id = row['user_id']
    linux_user = row['linux_user']
    if not isinstance(user_id, str) or not valid_id(user_id):
        raise ProvisionError('Invalid member ID')
    if not isinstance(linux_user, str) or not LINUX_USER.fullmatch(linux_user):
        raise ProvisionError('Invalid managed username')
    if linux_user != 'hbdesk_' + user_id[:16]:
        raise ProvisionError('Managed username mismatch')
    return user_id, linux_user


def active_request(row):
    identity(row)
    if row['status'] not in STATUSES:
        raise ProvisionError('Invalid request state')
    for field in ('requested_at', 'updated_at'):
        if type(row[field]) is not int or row[field] <= 0:
            raise ProvisionError('Invalid request timestamp')
    for field in ('approved_at', 'applied_at'):
        if row[field] is not None and (type(row[field]) is not int or row[field] <= 0):
            raise ProvisionError('Invalid approval timestamp')
    if row['approved_by'] is not None and not valid_id(row['approved_by']):
        raise ProvisionError('Invalid approver')
    if row['status'] not in ('approved', 'ready'):
        return False
    if not row['email_verified_at'] or not row['registration_completed_at']:
        return False
    if not row['approved_by'] or not row['approved_at']:
        raise ProvisionError('Approval record missing')
    try:
        if row['public_key']:
            validate_public_key(row['public_key'])
    except ValueError as error:
        raise ProvisionError('Invalid SSH key') from error
    password_hash = row['password_hash']
    if not isinstance(password_hash, str) or len(password_hash) > 160 or not SHA512_CRYPT.fullmatch(password_hash):
        raise ProvisionError('Invalid password hash')
    return True


def authorized_key(public_key):
    if not public_key:
        return b''
    key = validate_public_key(public_key)
    return ('restrict,port-forwarding,permitopen="127.0.0.1:3389",'
            'command="/usr/sbin/nologin" ' + key + '\n').encode('ascii')


class PosixSystem:
    """Small injectable boundary around account-management commands and NSS."""

    @staticmethod
    def user(name):
        import pwd
        try:
            return pwd.getpwnam(name)
        except KeyError:
            return None

    @staticmethod
    def group(name):
        import grp
        try:
            return grp.getgrnam(name)
        except KeyError:
            return None

    @staticmethod
    def group_by_gid(gid):
        import grp
        try:
            return grp.getgrgid(gid)
        except KeyError:
            return None

    @staticmethod
    def groups(name):
        import grp
        return {group.gr_name for group in grp.getgrall() if name in group.gr_mem}

    @staticmethod
    def run(args, *, input_text=None, allow_failure=False):
        # Never put a password hash in argv, stderr logs, or a shell command.
        try:
            result = subprocess.run(args, input=input_text, capture_output=True,
                                    text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProvisionError('Account helper unavailable') from error
        if result.returncode and not allow_failure:
            if args[0] == '/usr/sbin/useradd':
                LOG.error('useradd failed (%s): %.300s', result.returncode, result.stderr)
            raise ProvisionError('Account helper failed')
        return result

    def shadow_hash(self, name):
        result = self.run(['/usr/bin/getent', 'shadow', name])
        fields = result.stdout.strip().split(':')
        if len(fields) < 2 or fields[0] != name:
            raise ProvisionError('Shadow entry mismatch')
        return fields[1]

    def has_processes(self, uid):
        result = self.run(['/usr/bin/pgrep', '-u', str(uid)], allow_failure=True)
        if result.returncode not in (0, 1):
            raise ProvisionError('Could not inspect account sessions')
        return result.returncode == 0


class ManagedFilesystem:
    """Use directory descriptors so a tenant cannot redirect root writes via symlinks."""

    def __init__(self, home_root='/home', marker_root='/var/lib/habang-desktops', root_uid=0):
        self.home_root = Path(home_root)
        self.marker_root = Path(marker_root)
        self.root_uid = root_uid

    @staticmethod
    def _directory(path):
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    @staticmethod
    def _read_at(directory, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ProvisionError('Managed file is not regular')
            return os.read(fd, 4097), info
        finally:
            os.close(fd)

    @staticmethod
    def _write_at(directory, name, data, uid, gid):
        temporary = '.' + name + '.' + secrets.token_hex(8) + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            os.fchown(fd, uid, gid)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb', closefd=False) as output:
                output.write(data)
                output.flush()
            os.fsync(fd)
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(fd)

    def _marker_directory(self):
        self.marker_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = self._directory(self.marker_root)
        info = os.fstat(fd)
        if info.st_uid != self.root_uid or not stat.S_ISDIR(info.st_mode):
            os.close(fd)
            raise ProvisionError('Managed marker directory has wrong owner')
        os.fchmod(fd, 0o700)
        return fd

    @staticmethod
    def _marker_data(user_id, account):
        return f'{user_id}:{account.pw_uid}:{account.pw_gid}\n'.encode('ascii')

    def marker_present(self, name):
        directory = self._marker_directory()
        try:
            return self._read_at(directory, name) is not None
        finally:
            os.close(directory)

    def ensure_marker(self, user_id, account):
        directory = self._marker_directory()
        try:
            existing = self._read_at(directory, account.pw_name)
            expected = self._marker_data(user_id, account)
            if existing is None:
                self._write_at(directory, account.pw_name, expected, self.root_uid, 0)
            elif (existing[0] != expected or existing[1].st_uid != self.root_uid
                  or stat.S_IMODE(existing[1].st_mode) != 0o600):
                raise ProvisionError('Managed marker mismatch')
        finally:
            os.close(directory)

    def managed_accounts(self):
        directory = self._marker_directory()
        try:
            result = []
            for name in os.listdir(directory):
                if not LINUX_USER.fullmatch(name):
                    continue
                item = self._read_at(directory, name)
                if item is None or item[1].st_uid != self.root_uid:
                    raise ProvisionError('Managed marker missing or unowned')
                try:
                    user_id, uid, gid = item[0].decode('ascii').strip().split(':')
                    if not valid_id(user_id) or name != 'hbdesk_' + user_id[:16]:
                        raise ValueError()
                    int(uid), int(gid)
                except (ValueError, UnicodeError) as error:
                    raise ProvisionError('Invalid managed marker') from error
                result.append({'user_id': user_id, 'linux_user': name})
            return result
        finally:
            os.close(directory)

    def _home_directory(self, account):
        fd = self._directory(account.pw_dir)
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid
                or info.st_gid != account.pw_gid):
            os.close(fd)
            raise ProvisionError('Managed home ownership mismatch')
        os.fchmod(fd, 0o700)
        return fd

    @staticmethod
    def _ssh_directory(home, account, create=False):
        created = False
        if create:
            try:
                os.mkdir('.ssh', mode=0o700, dir_fd=home)
                created = True
            except FileExistsError:
                pass
        try:
            fd = os.open('.ssh', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home)
        except FileNotFoundError:
            return None
        if created:
            os.fchown(fd, account.pw_uid, account.pw_gid)
        info = os.fstat(fd)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != account.pw_uid
                or info.st_gid != account.pw_gid):
            os.close(fd)
            raise ProvisionError('Managed SSH directory ownership mismatch')
        os.fchmod(fd, 0o700)
        return fd

    def read_key(self, account):
        home = self._home_directory(account)
        try:
            ssh = self._ssh_directory(home, account)
            if ssh is None:
                return None
            try:
                item = self._read_at(ssh, 'authorized_keys')
                if item is None:
                    return None
                if item[1].st_uid != account.pw_uid or item[1].st_gid != account.pw_gid:
                    raise ProvisionError('Managed SSH key ownership mismatch')
                return item[0]
            finally:
                os.close(ssh)
        finally:
            os.close(home)

    def write_key(self, account, content):
        home = self._home_directory(account)
        try:
            ssh = self._ssh_directory(home, account, create=True)
            try:
                self._write_at(ssh, 'authorized_keys', content, account.pw_uid, account.pw_gid)
            finally:
                os.close(ssh)
        finally:
            os.close(home)

    def remove_key(self, account):
        home = self._home_directory(account)
        try:
            ssh = self._ssh_directory(home, account)
            if ssh is None:
                return
            try:
                try:
                    os.unlink('authorized_keys', dir_fd=ssh)
                except FileNotFoundError:
                    pass
            finally:
                os.close(ssh)
        finally:
            os.close(home)

    def read_xsession(self, account):
        home = self._home_directory(account)
        try:
            item = self._read_at(home, '.xsession')
            if item is None:
                return None
            if item[1].st_uid != account.pw_uid or item[1].st_gid != account.pw_gid:
                raise ProvisionError('Managed desktop session ownership mismatch')
            return item[0]
        finally:
            os.close(home)

    def write_xsession(self, account):
        home = self._home_directory(account)
        try:
            self._write_at(home, '.xsession', XSESSION, account.pw_uid, account.pw_gid)
        finally:
            os.close(home)


class AccountRuntime:
    def __init__(self, system=None, files=None):
        self.system = system or PosixSystem()
        self.files = files or ManagedFilesystem()

    def _account(self, row):
        user_id, name = identity(row)
        account = self.system.user(name)
        if account is None:
            return None
        if (account.pw_name != name or account.pw_gecos != f'{MARKER} {user_id}'
                or not 1001 <= account.pw_uid < 60000
                or account.pw_dir != str(self.files.home_root / name)
                or account.pw_shell != '/bin/bash'):
            raise ProvisionError('Existing account is not managed')
        primary = self.system.group_by_gid(account.pw_gid)
        if primary is None or primary.gr_name != name:
            raise ProvisionError('Managed primary group mismatch')
        self.files.ensure_marker(user_id, account)
        return account

    def _group(self):
        group = self.system.group(GROUP)
        if group is None:
            self.system.run(['/usr/sbin/groupadd', '--system', GROUP])
            group = self.system.group(GROUP)
        if group is None or group.gr_gid == 0:
            raise ProvisionError('Managed desktop group unavailable')
        return group

    def managed_accounts(self):
        return self.files.managed_accounts()

    def is_current(self, row):
        account = self._account(row)
        if account is None or self.system.group(GROUP) is None:
            return False
        return (self.system.groups(account.pw_name) == {GROUP}
                and self.files.read_key(account) == authorized_key(row['public_key'])
                and self.files.read_xsession(account) == XSESSION
                and self.system.shadow_hash(account.pw_name) == row['password_hash'])

    def provision(self, row):
        user_id, name = identity(row)
        self._group()
        account = self.system.user(name)
        if account is None:
            if self.files.marker_present(name):
                raise ProvisionError('Managed account disappeared')
            self.system.run(['/usr/sbin/useradd', '-m', '-U', '-G', GROUP,
                             '-s', '/bin/bash', '-d', str(self.files.home_root / name),
                             '-c', f'{MARKER} {user_id}', '-K', 'HOME_MODE=0700', name])
        account = self._account(row)
        if account is None:
            raise ProvisionError('Managed account was not created')
        if self.system.groups(name) != {GROUP}:
            self.system.run(['/usr/sbin/usermod', '-G', GROUP, name])
        if self.system.groups(name) != {GROUP}:
            raise ProvisionError('Managed group isolation failed')
        self.files.write_xsession(account)
        self.files.write_key(account, authorized_key(row['public_key']))
        if self.system.shadow_hash(name) != row['password_hash']:
            self.system.run(['/usr/sbin/chpasswd', '-e'],
                            input_text=f'{name}:{row["password_hash"]}\n')
        if self.system.shadow_hash(name) != row['password_hash']:
            raise ProvisionError('Managed password was not activated')
        self.system.run(['/usr/bin/chage', '-E', '-1', name])

    def deactivate(self, row):
        account = self._account(row)
        if account is None:
            return
        failed = False
        try:
            # Password locking alone does not reliably disable SSH public keys.
            self.system.run(['/usr/sbin/usermod', '--expiredate', '1', account.pw_name])
        except ProvisionError:
            failed = True
        try:
            self.files.remove_key(account)
        except (OSError, ProvisionError):
            failed = True
        # Lock and terminate even if the user's .ssh directory was tampered with.
        try:
            if not self.system.shadow_hash(account.pw_name).startswith('!'):
                self.system.run(['/usr/sbin/usermod', '-L', account.pw_name])
            if self.system.has_processes(account.pw_uid):
                self.system.run(['/usr/bin/loginctl', 'terminate-user', account.pw_name], allow_failure=True)
                self.system.run(['/usr/bin/pkill', '-KILL', '-u', str(account.pw_uid)], allow_failure=True)
        except ProvisionError:
            failed = True
        if failed:
            raise ProvisionError('Could not fully disable managed account')


class Worker:
    def __init__(self, database, runtime, clock=time.time):
        self.db = sqlite3.connect(database, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA busy_timeout=10000')
        self.runtime = runtime
        self.clock = clock

    def close(self):
        self.db.close()

    def _rows(self):
        return self.db.execute('''SELECT r.*,u.email_verified_at,u.registration_completed_at
                                  FROM host_desktop_requests AS r
                                  LEFT JOIN users AS u ON u.id=r.user_id''').fetchall()

    def _fresh(self, user_id):
        return self.db.execute('''SELECT r.*,u.email_verified_at,u.registration_completed_at
                                  FROM host_desktop_requests AS r
                                  LEFT JOIN users AS u ON u.id=r.user_id
                                  WHERE r.user_id=?''', (user_id,)).fetchone()

    def _failed(self, user_id, message=ERROR):
        with self.db:
            self.db.execute('''UPDATE host_desktop_requests
                               SET status='failed',last_error=?,updated_at=?
                               WHERE user_id=? AND status IN ('approved','ready','failed')''',
                            (message, int(self.clock()), user_id))

    def run_once(self):
        rows = self._rows()
        known = set()
        for original in rows:
            row = dict(original)
            user_id = row['user_id']
            known.add(user_id)
            try:
                active = active_request(row)
            except (ValueError, ProvisionError, TypeError):
                # A malformed SSH key or password must disable an existing account.
                if isinstance(user_id, str) and valid_id(user_id):
                    safe = {'user_id': user_id, 'linux_user': 'hbdesk_' + user_id[:16]}
                    try:
                        self.runtime.deactivate(safe)
                    except (OSError, ProvisionError):
                        LOG.error('Could not disable malformed desktop request for %s', user_id)
                    self._failed(user_id)
                continue
            try:
                if not active:
                    self.runtime.deactivate(row)
                    if row['status'] in ('approved', 'ready'):
                        self._failed(user_id, UNVERIFIED)
                    continue
                changed = row['status'] == 'approved' or not self.runtime.is_current(row)
                if changed:
                    self.runtime.provision(row)
                latest = self._fresh(user_id)
                if (latest is None or not active_request(latest)
                        or any(latest[field] != row[field] for field in
                               ('linux_user', 'public_key', 'password_hash', 'approved_by', 'approved_at'))):
                    self.runtime.deactivate(row)
                    continue
                if changed or row['applied_at'] is None:
                    now = int(self.clock())
                    with self.db:
                        result = self.db.execute('''UPDATE host_desktop_requests
                            SET status='ready',applied_at=?,updated_at=?,last_error=NULL
                            WHERE user_id=? AND status IN ('approved','ready')
                              AND linux_user=? AND public_key=? AND password_hash=?
                              AND EXISTS (SELECT 1 FROM users WHERE id=?
                                AND email_verified_at IS NOT NULL
                                AND registration_completed_at IS NOT NULL)''',
                            (now, now, user_id, row['linux_user'], row['public_key'],
                             row['password_hash'], user_id))
                    if result.rowcount != 1:
                        self.runtime.deactivate(row)
            except (OSError, ProvisionError, sqlite3.Error):
                LOG.error('Managed desktop reconciliation failed for %s', user_id)
                try:
                    self.runtime.deactivate(row)
                except (OSError, ProvisionError):
                    LOG.error('Managed desktop could not be disabled for %s', user_id)
                self._failed(user_id)
        try:
            for account in self.runtime.managed_accounts():
                if account['user_id'] not in known:
                    self.runtime.deactivate(account)
        except (OSError, ProvisionError):
            LOG.error('Could not reconcile orphaned managed desktops')


def main():
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise SystemExit('host_desktop_worker must run as root')
    import fcntl
    lock = os.open('/run/habang-host-desktop.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    logging.basicConfig(level=logging.INFO)
    worker = Worker(os.environ.get('HOST_DESKTOP_DATABASE', '/srv/files/data/community.sqlite3'),
                    AccountRuntime())
    try:
        while True:
            try:
                worker.run_once()
            except sqlite3.Error:
                LOG.error('Desktop database unavailable')
            time.sleep(3)
    finally:
        worker.close()
        os.close(lock)


if __name__ == '__main__':
    main()
