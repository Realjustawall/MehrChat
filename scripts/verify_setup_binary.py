"""Exercise packaged interactive setup without a domain or live-system changes."""
import json
import subprocess
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.tls import server_context

binary = Path(__file__).resolve().parent.parent/'dist/MehrRelay'
with tempfile.TemporaryDirectory() as directory:
    result = subprocess.run([str(binary), '--data', directory, '--setup'],
                            input='test_admin\nTemporary-Test-040!\nTemporary-Test-040!\n127.0.0.1\ny\n\n\n',
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    root = Path(directory)
    profile = json.loads((root/'client-profile.json').read_text())
    assert profile['locked'] and profile['relay']['transport'] == 'tls-noise'
    account = json.loads((root/'admin-account.json').read_text())
    assert account['password_hash'].startswith('$argon2id$')
    assert 'Temporary-Test-040!' not in json.dumps(account)
    server_context(root/'tls-cert.pem', root/'tls-key.pem')
    print('Packaged wizard: password hashing, confirmed IP, public profile and TLS pair: PASS')
