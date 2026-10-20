"""Exercise the actual interactive source installer on a disposable Ubuntu CI host."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.connection import probe
from mehrchat.crypto import create_identity, public_card
from mehrchat.wire import connect

assert os.environ.get('GITHUB_ACTIONS') == 'true' and sys.platform.startswith('linux'), 'Disposable Ubuntu Actions runner only'
root = Path(__file__).resolve().parent.parent
password = 'CI-only secure installer password 2026'
answers = ['ci_admin', password, password, '127.0.0.1', '', '', '8787', 'n']

def install(upgrade=False):
    data = '\n'.join((['y'] if upgrade else []) + answers) + '\n'
    result = subprocess.run(['sudo', 'bash', 'deploy/install-ubuntu.sh'], cwd=root, input=data, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    # Never print credential input, even if a future installer changes its logging.
    print(result.stdout.replace(password, '[redacted]'))
    assert result.returncode == 0, 'Interactive source installation failed'

def public(path):
    return subprocess.check_output(['sudo','cat',str(path)], text=True)

async def protocol(profile):
    assert (await probe(profile))['ok'] is True
    identity = create_identity('secure_ci', 'Secure CI')
    channel = await connect(profile['host'], profile['port'], profile['pin'], identity, public_card(identity),
                            transport='tls', ca=profile['ca'])
    try:
        await channel.send({'op':'settings'})
        assert (await channel.recv())['files_enabled'] is True
    finally:
        await channel.close()

try:
    install()
    profile_path = Path('/var/lib/mehrchat/client-profile.json')
    profile = json.loads(public(profile_path))
    assert profile['transport'] == 'tls'
    ca_before = public(Path('/var/lib/mehrchat/tls/ca.pem'))
    def admin(user, secret):
        data = urllib.parse.urlencode(dict(username=user, token=secret, files='yes')).encode()
        return urllib.request.urlopen('http://127.0.0.1:8788',data=data,timeout=5)
    try:
        admin('wrong_admin',password)
    except urllib.error.HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError('Admin accepted a wrong username')
    with admin('ci_admin',password) as response:
        assert response.status == 200
    asyncio.run(protocol(profile))
    install(upgrade=True)
    upgraded = json.loads(public(profile_path))
    assert upgraded['pin'] == profile['pin'] and upgraded['ca'] == profile['ca']
    assert public(Path('/var/lib/mehrchat/tls/ca.pem')) == ca_before
    asyncio.run(protocol(upgraded))
    subprocess.run(['sudo','systemctl','is-active','--quiet','mehr-tls-renew.timer'],check=True)
    # Credentials are a salted verifier, and service/certificate files are private.
    credentials = public(Path('/var/lib/mehrchat/admin-credentials.json'))
    assert password not in credentials
    for file in ['admin-credentials.json','tls/ca-key.pem','tls/server-key.pem']:
        mode = subprocess.check_output(['sudo','stat','-c','%a','/var/lib/mehrchat/'+file],text=True).strip()
        assert mode == '600', (file,mode)
    print('Interactive Ubuntu install / admin authentication / verified TLS+Noise / upgrade identity+CA retention / renewal timer: PASS')
finally:
    subprocess.run(['sudo','systemctl','disable','--now','mehr-tls-renew.timer','mehr-relay'],check=False)
