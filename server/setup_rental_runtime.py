"""One-time host preparation. Run with sudo; contains no account passwords."""
import grp
import json
import os
from pathlib import Path
import pwd
import subprocess

def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, cwd='/srv/files').stdout.strip()

try:
    grp.getgrnam('habang-data')
except KeyError:
    command('groupadd', '--system', 'habang-data')
try:
    account = pwd.getpwnam('habang-rentals')
except KeyError:
    command('useradd', '--system', '--create-home', '--home-dir', '/var/lib/habang-rentals', '--shell', '/usr/sbin/nologin', '--user-group', 'habang-rentals')
    account = pwd.getpwnam('habang-rentals')
for username in ('habang222', 'habang-rentals'):
    command('usermod', '-aG', 'habang-data', username)
if not any(line.startswith('habang-rentals:') for line in Path('/etc/subuid').read_text().splitlines()):
    ranges = []
    for file in ('/etc/subuid', '/etc/subgid'):
        for line in Path(file).read_text().splitlines():
            _, start, count = line.split(':')
            ranges.append((int(start), int(start) + int(count)))
    first = 200000
    while any(first < end and first + 65536 > start for start, end in ranges):
        first += 65536
    command('usermod', '--add-subuids', f'{first}-{first+65535}', '--add-subgids', f'{first}-{first+65535}', 'habang-rentals')
data = Path('/srv/files/data')
data_group = grp.getgrnam('habang-data').gr_gid
os.chown('/srv/files', pwd.getpwnam('habang222').pw_uid, data_group)
Path('/srv/files').chmod(0o750)
os.chown(data, pwd.getpwnam('habang222').pw_uid, data_group)
data.chmod(0o2770)
for file in data.glob('community.sqlite3*'):
    os.chown(file, pwd.getpwnam('habang222').pw_uid, data_group)
    file.chmod(0o660)
command('loginctl', 'enable-linger', 'habang-rentals')
command('systemctl', 'start', f'user@{account.pw_uid}.service')
values = {'HOME': account.pw_dir, 'XDG_RUNTIME_DIR': f'/run/user/{account.pw_uid}',
          'DBUS_SESSION_BUS_ADDRESS': f'unix:path=/run/user/{account.pw_uid}/bus',
          'DATABASE': '/srv/files/data/community.sqlite3', 'RENTAL_STATE': account.pw_dir + '/instances',
          'RENTAL_BIND_ADDRESS': '100.110.205.65', 'RENTAL_MAX_INSTANCES': '2',
          'RENTAL_IMAGE': 'localhost/habang-workspace:1'}
path = Path('/srv/files/config/rental-worker.env')
path.write_text(''.join(k + '=' + v + '\n' for k, v in values.items()))
path.chmod(0o600)
args = ['runuser', '-u', 'habang-rentals', '--', 'env', *(k + '=' + v for k, v in values.items())]
info = json.loads(command(*args, '/usr/bin/podman', 'info', '--format', 'json'))
print(json.dumps({'uid': account.pw_uid, 'home': account.pw_dir, 'rootless': info['host']['security']['rootless'], 'cgroups': info['host']['cgroupVersion'], 'controllers': info['host']['cgroupControllers']}))
