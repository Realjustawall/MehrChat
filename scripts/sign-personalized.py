"""Sign downloaded deployment APKs locally. The key never goes to CI."""
import argparse
import getpass
import os
import shutil
import subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('directory',type=Path)
    a=p.parse_args()
    if not shutil.which('apksigner') or not shutil.which('keytool'):
        raise RuntimeError('Install apksigner and default-jre-headless first')
    apks=list(a.directory.rglob('*release-unsigned.apk'))
    if not apks:raise RuntimeError('No unsigned release APK found')
    value=input('Existing PKCS12/JKS path (blank to create a new deployment key): ').strip()
    key=Path(value).expanduser() if value else a.directory/'deployment-signing.p12'
    alias=input('Key alias [mehrchat]: ').strip() or 'mehrchat'
    password=getpass.getpass('Signing key password (at least 12 characters): ')
    if len(password)<12:raise ValueError('Use at least 12 characters')
    env=os.environ.copy();env['MEHRCHAT_SIGN_PASSWORD']=password
    if not value:
        if password!=getpass.getpass('Repeat signing password: '):raise ValueError('Passwords do not match')
        if key.exists():raise ValueError('Signing key already exists; select it explicitly')
        previous=os.umask(0o077)
        try:
            subprocess.run(['keytool','-genkeypair','-keystore',str(key),'-storetype','PKCS12','-alias',alias,'-keyalg','RSA','-keysize','4096','-validity','10000','-dname','CN=MehrChat Deployment','-storepass:env','MEHRCHAT_SIGN_PASSWORD','-keypass:env','MEHRCHAT_SIGN_PASSWORD'],env=env,check=True)
        finally:os.umask(previous)
    for apk in apks:
        output=apk.with_name(apk.name.replace('-release-unsigned','-release-signed'))
        if output.exists():raise ValueError('Signed output already exists')
        # Preserve the already aligned Gradle APK entry offsets. Signing adds a
        # signing block without moving library payload entries.
        subprocess.run(['apksigner','sign','--ks',str(key),'--ks-key-alias',alias,'--ks-pass','env:MEHRCHAT_SIGN_PASSWORD','--key-pass','env:MEHRCHAT_SIGN_PASSWORD','--out',str(output),str(apk)],env=env,check=True)
        subprocess.run(['apksigner','verify','--verbose',str(output)],check=True)
        print('Installable dedicated release:',output)
    print('Back up your signing key and remember its password. Reuse this key for every update.')


if __name__=='__main__':main()
