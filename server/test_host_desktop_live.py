"""Explicit root QA: creates and removes one disposable host account, never the site DB."""
import os
from pathlib import Path
import pwd
import secrets
import signal
import sqlite3
import subprocess
import tempfile
import time

from host_desktop_worker import AccountRuntime, ManagedFilesystem, Worker


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, check=True, **kwargs)


def main():
    if os.geteuid() != 0 or os.environ.get('HOST_DESKTOP_QA') != '1':
        raise SystemExit('Run explicitly as root with HOST_DESKTOP_QA=1')
    user_id = secrets.token_hex(16)
    username = 'hbdesk_' + user_id[:16]
    account = None
    client = None
    worker = None
    with tempfile.TemporaryDirectory(prefix='habang-desktop-qa-') as temporary:
        folder = Path(temporary)
        try:
            key = folder / 'key'
            run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)])
            password = secrets.token_urlsafe(24)
            hashed = run(['/usr/bin/openssl', 'passwd', '-6', '-stdin'], input=(password+'\n').encode()).stdout.decode().strip()
            database = folder / 'qa.sqlite3'
            db = sqlite3.connect(database)
            db.executescript('''CREATE TABLE users(id TEXT PRIMARY KEY,email_verified_at INTEGER,registration_completed_at INTEGER);
              CREATE TABLE host_desktop_requests(user_id TEXT PRIMARY KEY,linux_user TEXT,public_key TEXT,password_hash TEXT,
              status TEXT,requested_at INTEGER,updated_at INTEGER,approved_by TEXT,approved_at INTEGER,applied_at INTEGER,last_error TEXT);''')
            db.execute('INSERT INTO users VALUES(?,1,1)', (user_id,))
            db.execute('INSERT INTO host_desktop_requests VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (user_id,username,key.with_suffix('.pub').read_text().strip(),hashed,'approved',1,1,user_id,1,None,None))
            db.commit()
            worker = Worker(str(database), AccountRuntime(files=ManagedFilesystem(marker_root=folder/'markers')))
            worker.runtime.provision(worker._rows()[0])
            worker.run_once()
            assert db.execute('SELECT status FROM host_desktop_requests').fetchone()[0] == 'ready'
            account = pwd.getpwnam(username)
            assert Path(account.pw_dir).stat().st_mode & 0o777 == 0o700
            groups = run(['/usr/bin/id', '-nG', username]).stdout.decode().split()
            assert set(groups) == {username, 'hbdesktop'}, groups
            if os.environ.get('HOST_DESKTOP_QA_PROVISION_ONLY') == '1':
                db.execute("UPDATE host_desktop_requests SET status='revoked'")
                db.commit()
                worker.run_once()
                db.close()
                print('HOST_DESKTOP_SERVICE_PROVISION_AND_REVOKE_OK')
                return
            known_hosts = folder / 'known_hosts'
            public_host = Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().split()
            known_hosts.write_text('127.0.0.1 ' + ' '.join(public_host[:2]) + '\n')
            ssh = ['/usr/bin/ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                   '-o','UserKnownHostsFile='+str(known_hosts),'-i',str(key)]
            shell = subprocess.run(ssh+[username+'@127.0.0.1','true'],capture_output=True,timeout=10)
            assert shell.returncode != 0, 'Member obtained a host SSH shell'
            blocked = subprocess.run(ssh+['-W','127.0.0.1:8080',username+'@127.0.0.1'],capture_output=True,timeout=10)
            assert blocked.returncode != 0, 'Member forwarded an unapproved port'
            client = subprocess.Popen(['/usr/bin/xvfb-run','-a','/usr/bin/xfreerdp3',
                '/v:127.0.0.1:3389','/u:'+username,'/p:'+password,'/cert:ignore',
                '/size:1024x768','/log-level:ERROR'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=True)
            desktop_ready = False
            for _ in range(40):
                result = subprocess.run(['/usr/bin/pgrep','-u',str(account.pw_uid),'-x','xfce4-session'],capture_output=True)
                if result.returncode == 0:
                    desktop_ready = True
                    break
                if client.poll() is not None: break
                time.sleep(0.5)
            assert desktop_ready, 'Xfce session did not start'
            db.execute("UPDATE host_desktop_requests SET status='revoked'")
            db.commit()
            worker.run_once()
            rejected = subprocess.run(ssh+[username+'@127.0.0.1','true'],capture_output=True,timeout=10)
            assert rejected.returncode == 255, 'Revoked SSH credential still authenticated'
            assert subprocess.run(['/usr/bin/pgrep','-u',str(account.pw_uid)],capture_output=True).returncode == 1
            print('LIVE_HOST_DESKTOP_OK: isolated account, SSH restrictions, Xfce login, and revocation')
            db.close()
        finally:
            if worker: worker.close()
            if client and client.poll() is None:
                os.killpg(client.pid, signal.SIGTERM)
                try: client.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(client.pid, signal.SIGKILL)
            try: account = pwd.getpwnam(username)
            except KeyError: account = None
            if account:
                assert account.pw_gecos == 'habang-host-desktop '+user_id
                assert account.pw_dir == '/home/'+username
                subprocess.run(['/usr/bin/pkill','-KILL','-u',str(account.pw_uid)],capture_output=True)
                subprocess.run(['/usr/bin/umount',account.pw_dir+'/thinclient_drives'],capture_output=True)
                run(['/usr/sbin/userdel','--remove',username])


if __name__ == '__main__': main()
