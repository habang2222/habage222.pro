#!/bin/sh
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run as root' >&2; exit 1; }
install -o root -g root -m 644 /srv/files/app/host_desktop_worker.py /usr/local/lib/habang-host-desktop/host_desktop_worker.py
install -d -o root -g root -m 755 /etc/systemd/system/habang.service.d
cat > /etc/systemd/system/habang.service.d/browser-remote.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/srv/files/venv/bin/gunicorn --workers 2 --threads 8 --bind 127.0.0.1:8080 --timeout 40 --no-control-socket --error-logfile - app:create_app()
EOF
systemctl daemon-reload
systemctl restart habang-host-desktop
systemctl restart habang
systemctl is-active habang habang-guacd xrdp habang-host-desktop
