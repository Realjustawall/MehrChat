"""Public connection profiles. These deliberately contain no admin/user secrets."""
import json
import os
import tempfile
from pathlib import Path
from .crypto import dec
from .wire import validate_destination

DEFAULT_RELAY = {'host': '127.0.0.1', 'port': 8787, 'transport': 'tls-noise', 'pin': '', 'tls_pin': ''}


def validate_relay(value, complete=True):
    if not isinstance(value, dict) or set(value) - {'host', 'port', 'transport', 'pin', 'tls_pin'}:
        raise ValueError('Invalid connection profile')
    validate_destination(value['host'], value['port'])
    if value.get('transport', 'noise') not in ('noise', 'tls-noise'):
        raise ValueError('Unsupported transport')
    pin = value.get('pin', '')
    if not isinstance(pin,str):raise ValueError('Invalid Noise public key')
    if (complete or pin) and len(dec(pin)) != 32:
        raise ValueError('Invalid Noise public key')
    tls = value.get('tls_pin', '')
    if not isinstance(tls,str):raise ValueError('Invalid TLS public-key pin')
    if tls and (len(tls) != 64 or any(c not in '0123456789abcdef' for c in tls)):
        raise ValueError('Invalid TLS public-key pin')
    if value.get('transport', 'noise') == 'noise' and tls:
        raise ValueError('TLS pin supplied without TLS')
    return dict(value)


def validate_profile(value):
    if not isinstance(value, dict) or set(value) != {'v', 'locked', 'relay'} or type(value['v']) is not int or value['v'] != 1 or type(value['locked']) is not bool:
        raise ValueError('Invalid deployment profile')
    validate_relay(value['relay'])
    if value['locked'] and value['relay'].get('transport') != 'tls-noise':
        raise ValueError('Dedicated builds require TLS')
    return value


def read_profile(path):
    with Path(path).open(encoding='utf-8') as f:
        raw = f.read(8193)
    if len(raw.encode()) > 8192: raise ValueError('Profile too large')
    return validate_profile(json.loads(raw))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.config-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
