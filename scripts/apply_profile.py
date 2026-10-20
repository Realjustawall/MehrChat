"""Apply a validated public deployment profile to this build only."""
import base64
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.deployment import validate_profile, write_json

raw = os.environ.get('PROFILE_B64', '')
target = Path('assets/client-profile.json')
if raw:
    if len(raw) > 12000: raise ValueError('Deployment input too large')
    value = validate_profile(json.loads(base64.b64decode(raw, validate=True)))
    if not value['locked']: raise ValueError('Dedicated build profile must be locked')
    write_json(target, value)
    print('Validated dedicated TLS connection profile embedded; no private keys included.')
else:
    target.unlink(missing_ok=True)
    print('Standard configurable build.')
