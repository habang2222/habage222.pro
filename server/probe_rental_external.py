"""Root-side probe for the disposable rental verifier, without changing egress rules."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

if os.geteuid() != 0:
    raise SystemExit('Run as root')
folder = Path(sys.argv[1]).resolve()
assert folder.parent == Path('/tmp') and folder.name.startswith('habang-rental-qa-')
info = json.loads((folder/'probe.json').read_text())
assert info == {'host':'100.110.205.65','port':23019,'plan':'kali-workspace'}
ssh = ['/usr/bin/ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
       '-o','UserKnownHostsFile='+str(folder/'known_hosts'),'-o','ConnectTimeout=10',
       '-i',str(folder/'client-key'),'-p','23019','tenant@100.110.205.65']
program = """import os,json,pathlib,socket,urllib.request
assert os.getuid()==1000
assert 'ID=kali' in pathlib.Path('/etc/os-release').read_text()
assert pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip()==str(512*1024*1024)
assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip()=='64'
assert urllib.request.urlopen('http://127.0.0.1:6080/vnc.html',timeout=5).status==200
s=socket.create_connection(('127.0.0.1',5900),5)
assert s.recv(12).startswith(b'RFB ')
s.close()
print('KALI_OS_SSH_NOVNC_AND_LIMITS_OK')
"""
result = subprocess.run(ssh+['python3 -c '+shlex.quote(program)],capture_output=True,text=True,timeout=25)
if result.returncode:
    raise RuntimeError('External rental probe failed: '+result.stderr[-700:])
allowed = subprocess.run(ssh[:-1]+['-W','127.0.0.1:6080',ssh[-1]],
    input='GET /vnc.html HTTP/1.0\r\nHost: localhost\r\n\r\n',capture_output=True,text=True,timeout=15)
assert allowed.returncode==0 and '200 OK' in allowed.stdout
blocked = subprocess.run(ssh[:-1]+['-W','127.0.0.1:22',ssh[-1]],capture_output=True,text=True,timeout=15)
assert blocked.returncode!=0 and 'administratively prohibited' in blocked.stderr
(folder/'probe.done').write_text('ok')
print(result.stdout.strip()+'; ALLOWED_FORWARD_AND_DENIED_OTHER_PORT_OK')
