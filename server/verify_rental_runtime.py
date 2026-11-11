"""Disposable end-to-end rental test in a temporary DB, never production users."""
from pathlib import Path
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import create_app
from rental_worker import Runtime, Worker

with tempfile.TemporaryDirectory(prefix='habang-rental-qa-') as scratch:
    folder = Path(scratch)
    key = folder / 'client-key'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    database = str(folder / 'qa.sqlite3')
    app = create_app({'SECRET_KEY': 'runtime-test-only-' * 4, 'BASE_URL': 'https://qa.example',
                      'DATABASE': database, 'SITE_ROOT': str(Path(__file__).resolve().parents[1] / 'site'),
                      'ADMIN_USER_IDS': '', 'ALIAS_HOSTS': '', 'TRUST_PROXY': False,
                      'GOOGLE_CLIENT_ID': '', 'GOOGLE_CLIENT_SECRET': '', 'GITHUB_CLIENT_ID': '', 'GITHUB_CLIENT_SECRET': ''})
    identity = secrets.token_hex(16)
    rental = secrets.token_hex(16)
    stamp = int(time.time())
    with sqlite3.connect(database) as connection:
        connection.execute(
            'INSERT INTO users(id,email,password_hash,display_name,created_at,full_name,email_verified_at,registration_completed_at) '
            'VALUES(?,NULL,NULL,?,?,?,?,?)',
            (identity, 'Runtime QA', stamp, 'Runtime QA', stamp, stamp))
        connection.execute("INSERT INTO rentals(id,user_id,name,plan,public_key,status,created_at,updated_at) VALUES(?,?,?,'workspace',?,'queued',?,?)", (rental, identity, 'Disposable runtime test', key.with_suffix('.pub').read_text().strip(), stamp, stamp))
        connection.execute("INSERT INTO rental_jobs(id,rental_id,action,status,created_at) VALUES(?,?,'create','queued',?)", (secrets.token_hex(16), rental, stamp))
    runtime = Runtime()
    runtime.ready()
    worker = Worker(database, runtime)
    row = None
    try:
        worker.run_once()
        row = dict(worker.db.execute('SELECT * FROM rentals WHERE id=?', (rental,)).fetchone())
        if row['status'] != 'running':
            raise RuntimeError('Rental did not reach running: ' + row['status'])
        known_hosts = folder / 'known_hosts'
        host_public = (runtime.state / (rental + '.hostkey.pub')).read_text().strip()
        known_hosts.write_text(f'[{runtime.bind}]:{row["ssh_port"]} {host_public}\n')
        ssh = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known_hosts), '-o', 'ConnectTimeout=10', '-i', str(key), '-p', str(row['ssh_port']), 'tenant@' + runtime.bind]
        program = "import os,json,pathlib; p=pathlib.Path('/home/tenant/qa.txt');p.write_text('works');print(json.dumps({'uid':os.getuid(),'write':p.read_text(),'memory':pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip(),'cpu':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip(),'pids':pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip()}))"
        import shlex
        result = subprocess.run(ssh + ['python3 -c ' + shlex.quote(program)], capture_output=True, text=True, timeout=25, check=True)
        checks = json.loads(result.stdout)
        assert checks['uid'] == 1000 and checks['write'] == 'works'
        assert checks['memory'] == str(384 * 1024 * 1024) and checks['pids'] == '64'
        quota, period = checks['cpu'].split()
        assert int(quota) / int(period) == 0.5
        desktop_probe = ("import socket,urllib.request,json,pathlib;"
                         "r=urllib.request.urlopen('http://127.0.0.1:6080/vnc.html',timeout=5);"
                         "v=socket.create_connection(('127.0.0.1',5900),timeout=5);"
                         "print(json.dumps({'web':r.status,'vnc':v.recv(12).decode(),"
                         "'memory_used':int(pathlib.Path('/sys/fs/cgroup/memory.current').read_text())}))")
        desktop_result = subprocess.run(
            ssh + ['python3 -c ' + shlex.quote(desktop_probe)],
            capture_output=True, text=True, timeout=20)
        if desktop_result.returncode:
            raise RuntimeError('Desktop probe failed: ' + desktop_result.stderr[-700:])
        desktop = json.loads(desktop_result.stdout)
        assert desktop['web'] == 200 and desktop['vnc'].startswith('RFB ')
        assert desktop['memory_used'] < 384 * 1024 * 1024
        allowed = subprocess.run(
            ssh[:-1] + ['-W', '127.0.0.1:6080', ssh[-1]],
            input='GET /vnc.html HTTP/1.0\r\nHost: localhost\r\n\r\n',
            capture_output=True, text=True, timeout=15)
        assert allowed.returncode == 0 and '200 OK' in allowed.stdout
        forbidden = subprocess.run(
            ssh[:-1] + ['-W', '127.0.0.1:22', ssh[-1]],
            capture_output=True, text=True, timeout=15)
        assert forbidden.returncode != 0 and 'administratively prohibited' in forbidden.stderr
        fingerprint = row['ssh_fingerprint']
        runtime.operate('stop', row)
        new_fingerprint = runtime.operate('start', row)
        assert new_fingerprint == fingerprint
        result = subprocess.run(ssh + ["test ! -e /home/tenant/qa.txt"], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0
        runtime.operate('terminate', row)
        assert runtime.inspect(row) is None
        print(json.dumps({'rootless': True, 'ssh_login': True, 'checks': checks, 'desktop': desktop,
                          'desktop_ssh_forward': True, 'other_ssh_forward_denied': True,
                          'restart_keeps_host_key': True, 'temporary_files_reset': True,
                          'termination_verified': True}))
    finally:
        if row:
            runtime.operate('terminate', row)
        worker.db.close()
