"""Dependency cache identity; app version changes do not change native requirements."""
import configparser
import hashlib
from pathlib import Path
spec = configparser.ConfigParser(interpolation=None)
spec.read('buildozer.spec')
spec.remove_option('app', 'version')
digest = hashlib.sha256()
for section in spec.sections():
    for key, value in sorted(spec.items(section)):
        digest.update(f'{section}/{key}={value}\n'.encode())
for path in sorted([Path('requirements.txt'), Path('requirements-server.txt'), *Path('p4a-recipes').rglob('*.py')]):
    if '__pycache__' not in path.parts:
        digest.update(str(path).encode() + path.read_bytes())
print('key=' + digest.hexdigest())
