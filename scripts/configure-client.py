"""Compile only validated public deployment data into the client package."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.connection import validate_profile
parser = argparse.ArgumentParser()
parser.add_argument('--profile', type=Path)
args = parser.parse_args()
raw = args.profile.read_text() if args.profile else base64.b64decode(os.environ['MEHRCHAT_PROFILE'], validate=True).decode()
profile = validate_profile(json.loads(raw))
if profile['transport'] != 'tls':
    sys.exit('Dedicated builds require verified TLS.')
Path('mehrchat/_deployment.py').write_text('# Public deployment configuration; this is not a secret.\nPROFILE = ' + repr(profile) + '\n')
