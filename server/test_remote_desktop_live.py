"""Explicit root integration QA: disposable member/OS account, public WSS, cleanup.

No real member credentials or approvals are changed. Run only with
HOST_BROWSER_QA=1. Ephemeral records and home are removed in finally.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import secrets
import sqlite3
import subprocess
import time

from dotenv import dotenv_values
from simple_websocket import Client, ConnectionClosed, ConnectionError

from host_desktop import hash_desktop_password
from remote_desktop import Instructions, instruction


def main():
    if os.geteuid() != 0 or os.environ.get('HOST_BROWSER_QA') != '1':
        raise SystemExit('Explicit root HOST_BROWSER_QA=1 required')
    os.umask(0o007)
    import grp
    os.setgid(grp.getgrnam('habang-data').gr_gid)
    config = dotenv_values('/srv/files/config/community.env')
    origin = config['BASE_URL'].rstrip('/')
    db = sqlite3.connect('/srv/files/data/community.sqlite3',timeout=10)
    db.row_factory = sqlite3.Row
    user_id = secrets.token_hex(16)
    username = 'hbdesk_' + user_id[:16]
    token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(24)
    session_hash = hashlib.sha256(token.encode()).hexdigest()
    csrf = hmac.new(config['SECRET_KEY'].encode(),token.encode(),hashlib.sha256).hexdigest()
    now = int(time.time())
    ws = None
    row = None
    try:
        with db:
            db.execute('''INSERT INTO users(id,email,display_name,created_at,email_verified_at,registration_completed_at,full_name)
                        VALUES(?,?,?, ?,?,?,?)''',(user_id,user_id+'@example.invalid','Browser remote QA',now,now,now,'Disposable QA'))
            db.execute('INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)',
                        (session_hash,user_id,now+600,now))
            db.execute('''INSERT INTO host_desktop_requests
              (user_id,linux_user,public_key,password_hash,status,requested_at,updated_at,approved_by,approved_at,applied_at)
              VALUES(?,?,'',?,'approved',?,?,?,?,?)''',
              (user_id,username,hash_desktop_password(password),now,now,user_id,now,now))
        row = db.execute('''SELECT r.*,u.email_verified_at,u.registration_completed_at FROM host_desktop_requests r
                           JOIN users u ON u.id=r.user_id WHERE r.user_id=?''',(user_id,)).fetchone()
        # Only the running provisioner creates OS accounts. Concurrent useradd
        # calls from a test and the reconciler can create conflicting identities.
        for _ in range(60):
            current=db.execute('SELECT status FROM host_desktop_requests WHERE user_id=?',(user_id,)).fetchone()
            if current['status']=='ready':break
            if current['status']=='failed':raise AssertionError('Disposable account provisioning failed')
            time.sleep(.5)
        else:raise AssertionError('Disposable account provisioning timed out')
        url = origin.replace('https://','wss://')+'/api/remote/host'
        headers = {'Cookie':'__Host-habang_sid='+token,'Origin':origin}
        try:
            denied = Client.connect(url,headers={**headers,'Origin':'https://evil.example'},subprotocols=['guacamole'])
        except ConnectionError:
            pass
        else:
            denied.close(); raise AssertionError('Foreign Origin was accepted')
        bad = Client.connect(url,headers=headers,subprotocols=['guacamole'])
        bad.send(json.dumps({'csrfToken':'wrong','password':password,'width':1024,'height':768}))
        try:
            bad.receive(timeout=10)
            raise AssertionError('Bad CSRF not rejected')
        except ConnectionClosed:
            pass
        ws = Client.connect(url,headers=headers,subprotocols=['guacamole'])
        ws.send(json.dumps({'csrfToken':csrf,'password':password,'width':1024,'height':768}))
        parser = Instructions(4*1024*1024)
        rendered = False
        syncs = 0
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            packet = ws.receive(timeout=2)
            if packet is None:continue
            for values in parser.feed(packet):
                if values[0] == 'error':
                    raise AssertionError('RDP returned error code '+values[-1])
                if values[0] == 'sync':
                    syncs += 1
                    ws.send(instruction('sync',values[1]))
                if values[0] in ('png','jpeg','img'):
                    rendered = True
                if values[0] == 'blob':
                    ws.send(instruction('ack',values[1],'OK',0))
            if rendered and syncs >= 3:
                ready = subprocess.run(['/usr/bin/pgrep','-u',str(pwd.getpwnam(username).pw_uid),'-x','xfce4-session'],capture_output=True)
                if ready.returncode == 0: break
        else:
            raise AssertionError('No real Xfce display frames over public WSS')
        # Exercise input on the disposable desktop, never a real member session.
        ws.send(instruction('mouse',100,100,0)+instruction('key',65507,1)+instruction('key',65507,0))
        account=pwd.getpwnam(username)
        xfce_pid=subprocess.check_output(['/usr/bin/pgrep','-u',str(account.pw_uid),'-x','xfce4-session'],text=True).split()[0]
        environment=dict(item.split(b'=',1) for item in Path('/proc/'+xfce_pid+'/environ').read_bytes().split(b'\0') if b'=' in item)
        display=environment[b'DISPLAY'].decode()
        authority=environment.get(b'XAUTHORITY',str(Path(account.pw_dir)/'.Xauthority').encode()).decode()
        for _ in range(20):
            pointer=subprocess.run(['/usr/sbin/runuser','-u',username,'--','/usr/bin/env','DISPLAY='+display,
                'XAUTHORITY='+authority,'/usr/bin/xdotool','getmouselocation','--shell'],capture_output=True,text=True)
            if 'X=100\n' in pointer.stdout and 'Y=100\n' in pointer.stdout:break
            time.sleep(.1)
        else:raise AssertionError('Public WSS input did not move the real desktop pointer')
        with db:
            db.execute("UPDATE host_desktop_requests SET status='revoked' WHERE user_id=?",(user_id,))
        start = time.monotonic()
        while time.monotonic()-start < 6:
            try: ws.receive(timeout=1)
            except ConnectionClosed: break
        else:
            raise AssertionError('Approval revocation did not close live WebSocket')
        print('PUBLIC_BROWSER_REMOTE_OK: WSS through Cloudflare, real Xfce frames, input, Origin/CSRF denial, live revocation')
    finally:
        if ws:
            try: ws.close()
            except ConnectionClosed:pass
        with db:
            db.execute("UPDATE host_desktop_requests SET status='revoked' WHERE user_id=?",(user_id,))
        try: account=pwd.getpwnam(username)
        except KeyError:account=None
        if account:
            assert account.pw_gecos == 'habang-host-desktop '+user_id
            assert account.pw_dir == '/home/'+username
            subprocess.run(['/usr/sbin/usermod','--expiredate','1',username],check=True,capture_output=True)
            subprocess.run(['/usr/bin/pkill','-KILL','-u',str(account.pw_uid)],capture_output=True)
            result = subprocess.run(['/usr/sbin/userdel','--remove',username],capture_output=True)
            if result.returncode not in (0,12):
                raise AssertionError('Could not remove disposable QA account')
            # userdel can report 12 after removing the identity but leaving a
            # home. Only this exact freshly generated QA home may be removed.
            home=Path('/home')/username
            if home.exists():
                import shutil
                assert home.resolve()==home and not home.is_symlink()
                assert subprocess.run(['/usr/bin/mountpoint','-q',str(home)]).returncode!=0
                shutil.rmtree(home)
            marker=Path('/var/lib/habang-desktops')/username
            if marker.is_file():
                assert marker.read_text().startswith(user_id+':')
                marker.unlink()
        with db:
            for table,field in [('remote_connections','user_id'),('admin_events','actor_id'),('host_desktop_requests','user_id'),('sessions','user_id')]:
                db.execute(f'DELETE FROM {table} WHERE {field}=?',(user_id,))
            db.execute('DELETE FROM users WHERE id=?',(user_id,))
        db.close()


if __name__ == '__main__':main()
