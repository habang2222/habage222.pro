#!/bin/sh
set -eu
chown 1000:1000 /home/tenant
exec /usr/sbin/sshd -D -e
