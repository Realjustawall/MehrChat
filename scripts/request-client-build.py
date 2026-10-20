"""Dispatch, follow and download one dedicated build. Needs gh auth with Actions write."""
import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('profile', type=Path)
parser.add_argument('--repo', default='Realjustawall/MehrChat')
parser.add_argument('--ref', default='main')
parser.add_argument('--output', default='dedicated-clients')
args = parser.parse_args()
if not shutil.which('gh'):
    sys.exit('Install GitHub CLI and run gh auth login, then rerun this command.')
# Explicit allowlist: never send arbitrary server directory content or private keys.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.connection import validate_profile
profile = validate_profile(json.loads(args.profile.read_text()))
encoded = base64.b64encode(json.dumps(profile).encode()).decode()
request = uuid.uuid4().hex
subprocess.run(['gh', 'workflow', 'run', 'dedicated-clients.yml', '-R', args.repo, '--ref', args.ref,
                '-f', 'profile=' + encoded, '-f', 'request_id=' + request], check=True)
print('Requested build ' + request, flush=True)
for _ in range(60):
    runs = json.loads(subprocess.check_output(['gh', 'run', 'list', '-R', args.repo, '--workflow', 'dedicated-clients.yml', '--limit', '50', '--json', 'databaseId,displayTitle'], text=True))
    match = next((r for r in runs if r['displayTitle'] == 'Dedicated clients ' + request), None)
    if match:
        break
    time.sleep(2)
else:
    sys.exit('Build requested; locate it in GitHub Actions to download artifacts.')
run_id = str(match['databaseId'])
subprocess.run(['gh', 'run', 'watch', run_id, '-R', args.repo, '--exit-status'], check=True)
subprocess.run(['gh', 'run', 'download', run_id, '-R', args.repo, '--dir', args.output], check=True)
print('Downloaded artifacts to ' + args.output + '. Android release APK needs the owner signing key; debug APK is installable for testing.')
