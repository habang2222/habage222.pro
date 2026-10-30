"""Idempotent rootless Podman jobs. No web process gets runtime access."""
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import time

from rental_common import PLAN, RESERVED, TERMINAL, capacity_limit, valid_id, validate_public_key

LOG = logging.getLogger('habang-rentals')


class Runtime:
    def __init__(self):
        self.state = Path(os.environ.get('RENTAL_STATE', '/var/lib/habang-rentals/instances'))
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.bind = os.environ.get('RENTAL_BIND_ADDRESS', '100.110.205.65')
        self.image = os.environ.get('RENTAL_IMAGE', 'localhost/habang-workspace:1')

    def command(self, *args, timeout=45):
        result = subprocess.run(['/usr/bin/podman', *args], capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode:
            LOG.error('Podman %s failed: %.1200s', args[0], result.stderr)
            raise RuntimeError('컨테이너 작업에 실패했습니다. 관리자에게 문의해 주세요.')
        return result.stdout.strip()

    def ready(self):
        info = json.loads(self.command('info', '--format', 'json'))
        if not info.get('host', {}).get('security', {}).get('rootless'):
            raise RuntimeError('Rootless runtime required')
        if info.get('host', {}).get('cgroupVersion') != 'v2':
            raise RuntimeError('Cgroup v2 required')
        if not {'cpu', 'memory', 'pids'} <= set(info.get('host', {}).get('cgroupControllers', [])):
            raise RuntimeError('CPU/memory/process controllers must be delegated')
        self.image = self.command('image', 'inspect', '--format', '{{.Id}}', self.image)

    @staticmethod
    def name(row):
        if not valid_id(row['id']) or row['plan'] != PLAN['id']:
            raise RuntimeError('Invalid rental identity')
        return 'hb-rental-' + row['id']

    def inspect(self, row):
        name = self.name(row)
        exists = subprocess.run(['/usr/bin/podman', 'container', 'exists', name], capture_output=True)
        if exists.returncode == 1:
            return None
        if exists.returncode != 0:
            raise RuntimeError('Runtime unavailable')
        details = json.loads(self.command('inspect', name))[0]
        labels = details.get('Config', {}).get('Labels', {})
        if labels.get('pro.habang.rental') != row['id']:
            raise RuntimeError('Container ownership mismatch')
        return details

    def create(self, row):
        name = self.name(row)
        if not 23000 <= row['ssh_port'] < 23020:
            raise RuntimeError('Invalid assigned SSH port')
        public_key = validate_public_key(row['public_key'])
        details = self.inspect(row)
        if not details:
            existing = json.loads(self.command('ps', '-a', '--filter', 'label=pro.habang.managed=true', '--format', 'json'))
            if len(existing) >= capacity_limit():
                raise RuntimeError('Runtime capacity reached')
            key_path = self.state / (row['id'] + '.pub')
            key_path.write_text(public_key + '\n', encoding='ascii')
            key_path.chmod(0o644)
            host_key = self.state / (row['id'] + '.hostkey')
            if not host_key.exists():
                subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(host_key)], check=True, capture_output=True, timeout=10)
            host_key.chmod(0o600)
            self.command('create', '--name', name, '--label', 'pro.habang.managed=true',
                         '--label', 'pro.habang.rental=' + row['id'], '--hostname', 'workspace-' + row['id'][:8],
                         '--network', 'slirp4netns:allow_host_loopback=false,enable_ipv6=false',
                         '--publish', f'{self.bind}:{row["ssh_port"]}:2222',
                         '--cpus', str(PLAN['cpu']), '--memory', str(PLAN['memoryMb']) + 'm',
                         '--memory-swap', str(PLAN['memoryMb']) + 'm', '--pids-limit', str(PLAN['pids']),
                         '--ulimit', 'nofile=1024:2048', '--read-only', '--read-only-tmpfs=false',
                         '--tmpfs', f'/home/tenant:rw,size={PLAN["workspaceMb"]}m,mode=0700,nosuid,nodev',
                         '--tmpfs', f'/tmp:rw,size={PLAN["temporaryMb"]}m,mode=1777,nosuid,nodev',
                         '--tmpfs', '/run/sshd:rw,size=8m,mode=0755,nosuid,nodev',
                         '--mount', f'type=bind,src={key_path},destination=/run/tenant-key,ro=true',
                         '--mount', f'type=bind,src={host_key},destination=/run/workspace-host-key,ro=true',
                         '--cap-drop', 'all', '--cap-add', 'SETUID', '--cap-add', 'SETGID',
                         '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'SYS_CHROOT',
                         '--security-opt', 'no-new-privileges', '--log-driver', 'k8s-file',
                         '--log-opt', 'max-size=1mb', self.image)
            details = self.inspect(row)
        config = details.get('HostConfig', {})
        if config.get('Memory') != PLAN['memoryMb'] * 1024 * 1024 or config.get('PidsLimit') != PLAN['pids'] or not config.get('ReadonlyRootfs'):
            raise RuntimeError('Resource isolation is not active')
        self.command('start', name)
        return self.wait_for_ssh(row)

    def wait_for_ssh(self, row):
        for _ in range(20):
            try:
                with socket.create_connection((self.bind, row['ssh_port']), timeout=1) as channel:
                    channel.settimeout(2)
                    if channel.recv(120).startswith(b'SSH-2.0-'):
                        # The worker owns this public key. Read its fingerprint on
                        # the host; podman exec can cross a rootless cgroup boundary
                        # when the worker runs as a system service.
                        self.name(row)
                        public_key = self.state / (row['id'] + '.hostkey.pub')
                        result = subprocess.run(['/usr/bin/ssh-keygen', '-E', 'sha256', '-lf', str(public_key)],
                                                capture_output=True, text=True, check=True, timeout=10)
                        fingerprint = result.stdout.split()[1]
                        if not fingerprint.startswith('SHA256:'):
                            raise RuntimeError('Invalid host fingerprint')
                        return fingerprint
            except OSError:
                pass
            time.sleep(1)
        raise RuntimeError('SSH 서버가 시작되지 않았습니다. 관리자에게 문의해 주세요.')

    def operate(self, action, row):
        if action == 'create':
            return self.create(row)
        details = self.inspect(row)
        if action in ('terminate', 'expire'):
            if details:
                self.command('rm', '--force', self.name(row))
            key_path = self.state / (row['id'] + '.pub')
            key_path.unlink(missing_ok=True)
            (self.state / (row['id'] + '.hostkey')).unlink(missing_ok=True)
            (self.state / (row['id'] + '.hostkey.pub')).unlink(missing_ok=True)
            return None
        if not details:
            raise RuntimeError('대여 컨테이너를 찾을 수 없습니다.')
        if action not in ('start', 'stop', 'restart'):
            raise RuntimeError('Unsupported action')
        self.command(action, self.name(row))
        return self.wait_for_ssh(row) if action != 'stop' else None


class Worker:
    def __init__(self, database, runtime):
        self.db = sqlite3.connect(database, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.runtime = runtime

    def heartbeat(self, ready=True):
        with self.db:
            self.db.execute("INSERT INTO rental_runtime VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,ready=excluded.ready,message=excluded.message",
                            (int(time.time()), int(ready), 'ready' if ready else 'unavailable'))

    def expire(self):
        stamp = int(time.time())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            placeholders = ','.join('?' for _ in RESERVED)
            rows = self.db.execute(f"SELECT id FROM rentals WHERE expires_at<=? AND status IN ({placeholders}) AND status!='terminating'", (stamp, *RESERVED)).fetchall()
            for row in rows:
                # Wait for an in-flight operation; the next loop handles expiry.
                if self.db.execute("SELECT 1 FROM rental_jobs WHERE rental_id=? AND status='running' AND lease_until>?", (row['id'], stamp)).fetchone():
                    continue
                self.db.execute("UPDATE rental_jobs SET status='cancelled' WHERE rental_id=? AND status='queued'", (row['id'],))
                self.db.execute("UPDATE rentals SET status='terminating',updated_at=? WHERE id=?", (stamp, row['id']))
                self.db.execute("INSERT INTO rental_jobs(id,rental_id,action,status,created_at) VALUES(?,?,'expire','queued',?)", (secrets.token_hex(16), row['id'], stamp))

    def claim(self):
        stamp = int(time.time())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute("UPDATE rental_jobs SET status='queued' WHERE status='running' AND lease_until<?", (stamp,))
            job = self.db.execute("SELECT * FROM rental_jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not job:
                return None
            row = self.db.execute('SELECT * FROM rentals WHERE id=?', (job['rental_id'],)).fetchone()
            if row['status'] in TERMINAL:
                self.db.execute("UPDATE rental_jobs SET status='cancelled' WHERE id=?", (job['id'],))
                return None
            if job['action'] == 'create' and row['ssh_port'] is None:
                used = {r[0] for r in self.db.execute('SELECT ssh_port FROM rentals WHERE ssh_port IS NOT NULL')}
                port = next((p for p in range(23000, 23020) if p not in used), None)
                if port is None:
                    raise RuntimeError('No rental ports available')
                self.db.execute('UPDATE rentals SET ssh_port=? WHERE id=?', (port, row['id']))
            if job['action'] == 'create':
                self.db.execute("UPDATE rentals SET status='provisioning',updated_at=? WHERE id=?", (stamp, row['id']))
            self.db.execute("UPDATE rental_jobs SET status='running',lease_until=?,attempts=attempts+1 WHERE id=?", (stamp + 600, job['id']))
            return dict(job), dict(self.db.execute('SELECT * FROM rentals WHERE id=?', (row['id'],)).fetchone())

    def run_once(self):
        self.heartbeat()
        self.expire()
        item = self.claim()
        if not item:
            return False
        job, row = item
        try:
            fingerprint = self.runtime.operate(job['action'], row)
            target = {'create': 'running', 'start': 'running', 'stop': 'stopped', 'restart': 'running', 'terminate': 'terminated', 'expire': 'expired'}[job['action']]
            stamp = int(time.time())
            with self.db:
                self.db.execute("UPDATE rental_jobs SET status='done',lease_until=NULL WHERE id=?", (job['id'],))
                self.db.execute('UPDATE rentals SET status=?,updated_at=?,last_error=NULL,ssh_fingerprint=COALESCE(?,ssh_fingerprint),expires_at=COALESCE(expires_at,?) WHERE id=?',
                                (target, stamp, fingerprint, stamp + PLAN['durationHours'] * 3600, row['id']))
                if target in TERMINAL:
                    self.db.execute('UPDATE rentals SET ssh_port=NULL,ssh_fingerprint=NULL WHERE id=?', (row['id'],))
            LOG.info('Rental %s action %s completed', row['id'], job['action'])
        except Exception:
            LOG.exception('Rental %s action %s failed', row['id'], job['action'])
            with self.db:
                self.db.execute("UPDATE rental_jobs SET status='failed',lease_until=NULL WHERE id=?", (job['id'],))
                self.db.execute("UPDATE rentals SET status='failed',updated_at=?,last_error=? WHERE id=?", (int(time.time()), '서버 작업에 실패했습니다. 재시도하거나 관리자에게 문의해 주세요.', row['id']))
        self.heartbeat()
        return True


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    worker = Worker(os.environ['DATABASE'], Runtime())
    try:
        worker.runtime.ready()
        while True:
            worker.run_once()
            time.sleep(3)
    except Exception:
        worker.heartbeat(False)
        raise
