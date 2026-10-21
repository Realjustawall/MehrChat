"""Fail closed unless signed APK payload equals the tested unsigned APK."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

version = os.environ['RELEASE_VERSION']
assert re.fullmatch(r'\d+\.\d+\.\d+', version)
artifacts = Path('verified-artifacts')
out = Path('release-assets')
out.mkdir(exist_ok=True)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
signed = Path('signed-release.apk')
unsigned_files = list(artifacts.rglob(f'*{version}*arm64-v8a-release-unsigned.apk'))
assert len(unsigned_files) == 1, 'Exactly one tested phone release APK is required'
unsigned = unsigned_files[0]
assert digest(signed) == os.environ['SIGNED_APK_SHA256']
assert digest(unsigned) == os.environ['UNSIGNED_APK_SHA256']
def signature_entry(name):
    return bool(re.fullmatch(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', name, re.I))
with zipfile.ZipFile(unsigned) as a, zipfile.ZipFile(signed) as b:
    first = {n for n in a.namelist() if not signature_entry(n)}
    second = {n for n in b.namelist() if not signature_entry(n)}
    assert first == second, 'APK payload entries changed during signing'
    for name in sorted(first):
        assert a.read(name) == b.read(name), 'APK payload changed: ' + name
sdk = Path(os.environ.get('ANDROID_HOME', '/usr/local/lib/android/sdk'))
tools = sorted((sdk / 'build-tools').glob('*'), key=lambda p: [int(n) if n.isdigit() else n for n in re.split(r'(\d+)', p.name)])[-1]
verification = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(signed)], text=True)
assert 'Number of signers: 1' in verification
print(verification)
# Recent build-tools prefix certificate lines with SDK ranges instead of #1.
certificates = re.findall(r'(?im)^.*certificate SHA-256 digest:\s*([a-f0-9]{64})\s*$', verification)
assert certificates, 'Verifier did not print a certificate SHA-256 digest'
assert {value.lower() for value in certificates} == {os.environ['ANDROID_CERT_SHA256']}
subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(signed)], check=True)
(out / 'Android-signature-verification.txt').write_text(verification)
shutil.copyfile(signed, out / f'MehrChat-{version}-Android-arm64-v8a.apk')
for pattern in ('MehrChat-Windows-x64.zip','MehrChat-Ubuntu-x64.tar.gz'):
    files = list(artifacts.rglob(pattern))
    assert len(files) == 1, 'Missing tested desktop package: ' + pattern
    shutil.copyfile(files[0], out / pattern)
subprocess.run(['git', 'archive', '--format=tar.gz', '--prefix=MehrChat-'+version+'/', '-o', str(out / f'MehrChat-{version}-Server-Source.tar.gz'), 'HEAD'], check=True)
shutil.copyfile('README.md', out / 'INSTALLATION.md')
with zipfile.ZipFile(out / f'MehrChat-{version}-UI-Screenshots.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for platform in ('windows','android'):
        images = sorted(artifacts.glob('**/ui/'+platform+'/*.png'))
        assert len(images) >= 12, 'Missing real UI gallery: '+platform
        for image in images:
            archive.write(image, platform+'/'+image.name)
with zipfile.ZipFile(out / f'MehrChat-{version}-Validation-Reports.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for report in sorted(artifacts.rglob('*')):
        if report.is_file() and (report.suffix in ('.txt','.json','.log') or 'ui' in report.parts):
            archive.write(report, str(report.relative_to(artifacts)))
(out / 'SHA256SUMS.txt').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file() and p.name != 'SHA256SUMS.txt'))
print('Verified signed payload, owner certificate, 16 KiB alignment and complete release assets.')
