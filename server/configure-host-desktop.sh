#!/usr/bin/env bash
set -euo pipefail

# Run as root after installing xrdp and xorgxrdp while both units are masked.
# The RDP listener is loopback-only; SSH forwarding is limited to that listener.
if [[ $(id -u) -ne 0 ]]; then
    echo 'Run as root' >&2
    exit 1
fi
for package in xrdp xorgxrdp; do
    dpkg-query -W -f='${Status}' "$package" | grep -qx 'install ok installed'
done
if systemctl is-active --quiet xrdp.service; then
    echo 'Stop xrdp before changing its listener' >&2
    exit 1
fi

sshd_config=/etc/ssh/sshd_config
sshd_policy=/etc/ssh/sshd_config.d/00-habang-server.conf
xrdp_config=/etc/xrdp/xrdp.ini
for file in "$sshd_config" "$sshd_policy" "$xrdp_config"; do
    if [[ ! -f "$file" ]]; then
        echo "Missing $file" >&2
        exit 1
    fi
    if [[ ! -e "$file.habang-desktop.before" ]]; then
        cp -a "$file" "$file.habang-desktop.before"
    fi
done

getent group hbdesktop >/dev/null || groupadd --system hbdesktop
usermod -aG ssl-cert xrdp

python3 - "$xrdp_config" <<'PY'
from pathlib import Path
import re
import sys

file = Path(sys.argv[1])
content = file.read_text()
start = content.find('[Globals]')
end = content.find('\n[', start + 1)
if start < 0 or end < 0:
    raise SystemExit('Unexpected xrdp.ini layout')
updated, count = re.subn(r'(?m)^port=.*$', 'port=tcp://127.0.0.1:3389', content[start:end])
if count != 1:
    raise SystemExit('Expected exactly one global xrdp port')
updated = re.sub(r'(?m)^security_layer=.*$', 'security_layer=tls', updated)
content = content[:start] + updated + content[end:]
# Do not offer unauthenticated VNC/RDP proxy session types on the host.
sections = re.split(r'(?m)(?=^\[[^\]]+\])', content)
allowed = {'Globals', 'Logging', 'LoggingPerLogger', 'Channels', 'Xorg'}
file.write_text(''.join(part for part in sections if not part.startswith('[')
                       or part.split(']', 1)[0][1:] in allowed))
PY
sed -i 's/^AllowRootLogin=.*/AllowRootLogin=false/' /etc/xrdp/sesman.ini
sed -i 's/^#EnableFuseMount=false/EnableFuseMount=false/' /etc/xrdp/sesman.ini
sed -i 's/^rdpdr=true/rdpdr=false/' "$xrdp_config"

if grep -qx 'AllowUsers habang222' "$sshd_policy"; then
    sed -i 's/^AllowUsers habang222$/AllowUsers habang222 hbdesk_*/' "$sshd_policy"
elif ! grep -qx 'AllowUsers habang222 hbdesk_\*' "$sshd_policy"; then
    echo 'Unexpected SSH AllowUsers policy' >&2
    exit 1
fi

if ! grep -qx '# habang host desktop access' "$sshd_config"; then
    cat >> "$sshd_config" <<'EOF'

# habang host desktop access
Match User habang222
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:3389
    PermitTTY yes
Match Group hbdesktop
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:3389
    ForceCommand /usr/bin/false
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    AllowStreamLocalForwarding no
    PermitTunnel no
EOF
fi

if [[ ! -e /home/habang222/.xsession ]]; then
    printf 'xfce4-session\n' > /home/habang222/.xsession
    chown habang222:habang222 /home/habang222/.xsession
    chmod 600 /home/habang222/.xsession
fi

/usr/sbin/sshd -t
admin_settings=$(/usr/sbin/sshd -T -C user=habang222,host=habang,addr=100.110.205.65 | tr '[:upper:]' '[:lower:]')
grep -qx 'allowtcpforwarding local' <<< "$admin_settings"
grep -qx 'permitopen 127.0.0.1:3389' <<< "$admin_settings"
grep -qx 'passwordauthentication no' <<< "$admin_settings"

systemctl unmask xrdp.service xrdp-sesman.service
systemctl enable --now xrdp.service
systemctl reload ssh.service
for _ in {1..20}; do
    if ss -ltnH | grep -q '127.0.0.1:3389'; then break; fi
    sleep 0.25
done
if ! ss -ltnH | grep -Eq '^[^ ]+[[:space:]]+[^ ]+[[:space:]]+[^ ]+[[:space:]]+127\.0\.0\.1:3389[[:space:]]'; then
    systemctl stop xrdp.service
    echo 'xrdp did not bind to 127.0.0.1:3389' >&2
    exit 1
fi
if ss -ltnH | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]|\*):3389[[:space:]]'; then
    systemctl stop xrdp.service
    echo 'xrdp unexpectedly bound to a public interface' >&2
    exit 1
fi
echo 'Host RDP listens on loopback only; scoped SSH forwarding is enabled.'
