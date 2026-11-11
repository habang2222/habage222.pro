#!/bin/bash
set -euo pipefail
chown 1000:1000 /home/tenant
runuser -u tenant -- Xvfb :1 -screen 0 1280x800x24 -nolisten tcp &
xvfb_pid=$!
sleep 1
runuser -u tenant -- env DISPLAY=:1 openbox-session &
desktop_pid=$!
runuser -u tenant -- env DISPLAY=:1 xterm -geometry 110x30+40+40 &
terminal_pid=$!
runuser -u tenant -- env DISPLAY=:1 x11vnc -display :1 -localhost -rfbport 5900 -forever -shared -nopw -noxdamage -noshm -quiet &
vnc_pid=$!
runuser -u tenant -- websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 &
web_pid=$!
ssh_pid=
cleanup() {
    if [[ -n "$ssh_pid" ]]; then kill "$ssh_pid" 2>/dev/null || true; fi
    kill "$web_pid" "$vnc_pid" "$terminal_pid" "$desktop_pid" "$xvfb_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT TERM INT
ready=
for _ in {1..30}; do
    if python3 -c "import socket,urllib.request; urllib.request.urlopen('http://127.0.0.1:6080/vnc.html',timeout=1).close(); s=socket.create_connection(('127.0.0.1',5900),timeout=1); assert s.recv(4)==b'RFB '; s.close()" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.25
done
if [[ -z "$ready" ]]; then
    echo 'Desktop services failed to start' >&2
    exit 1
fi
/usr/sbin/sshd -D -e &
ssh_pid=$!
wait -n "$ssh_pid" "$web_pid" "$vnc_pid" "$xvfb_pid"
