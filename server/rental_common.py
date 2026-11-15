"""Fixed rental policy shared by the web app and the unprivileged worker."""
import base64
import os
import re
import struct

PLAN = {'id': 'workspace', 'name': 'Linux Workspace', 'cpu': 0.5, 'memoryMb': 384,
        'workspaceMb': 128, 'temporaryMb': 32, 'pids': 64, 'durationHours': 24}
TERMINAL = ('terminated', 'expired', 'cancelled', 'rejected')
RESERVED = ('queued', 'provisioning', 'running', 'stopped', 'starting', 'stopping',
            'restarting', 'terminating', 'failed')
TRANSITIONS = {'start': ('stopped',), 'stop': ('running',), 'restart': ('running',),
               'retry': ('failed',), 'terminate': ('queued', 'running', 'stopped', 'failed')}


def capacity_limit():
    return max(1, min(10, int(os.getenv('RENTAL_MAX_INSTANCES', '2'))))


def validate_public_key(value):
    """Accept a structurally valid ed25519/RSA key, never authorized_keys options."""
    if not isinstance(value, str) or len(value) > 1600 or '\n' in value.strip() or '\r' in value.strip():
        raise ValueError('SSH 공개키 한 줄을 입력해 주세요.')
    parts = value.strip().split()
    if len(parts) < 2 or parts[0] not in ('ssh-ed25519', 'ssh-rsa'):
        raise ValueError('ssh-ed25519 또는 ssh-rsa 공개키를 입력해 주세요.')
    try:
        raw = base64.b64decode(parts[1], validate=True)
        def field(offset):
            size = struct.unpack_from('>I', raw, offset)[0]
            end = offset + 4 + size
            if end > len(raw):
                raise ValueError()
            return raw[offset + 4:end], end
        kind, position = field(0)
        if kind.decode('ascii') != parts[0]:
            raise ValueError()
        if parts[0] == 'ssh-ed25519':
            key, position = field(position)
            if len(key) != 32:
                raise ValueError()
        else:
            exponent, position = field(position)
            modulus, position = field(position)
            if int.from_bytes(exponent, 'big') < 3 or int.from_bytes(modulus, 'big').bit_length() < 2048:
                raise ValueError()
        if position != len(raw):
            raise ValueError()
    except (ValueError, UnicodeError, struct.error):
        raise ValueError('올바른 SSH 공개키가 아닙니다.') from None
    return parts[0] + ' ' + parts[1]


def valid_id(value):
    return bool(re.fullmatch(r'[a-f0-9]{32}', value))
