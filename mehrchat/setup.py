"""Interactive server setup; only public pins are exported to clients."""
import getpass
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path
from nacl.pwhash import argon2id
from .deployment import write_json, validate_profile
from .tls import ensure_certificate, public_key_pin, server_context
from cryptography import x509
from cryptography.hazmat.primitives import serialization


def detected_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 9))
            return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def yes(prompt, default=False):
    return input(prompt + (' [Y/n]: ' if default else ' [y/N]: ')).strip().lower() in (('y', 'yes', '') if default else ('y', 'yes'))


def save_admin(root, username, password):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', username) or not 12 <= len(password) <= 1024:
        raise ValueError('Admin username: 4-32 letters/digits/underscore. Password: 12-1024 characters.')
    write_json(Path(root)/'admin-account.json', {'username': username, 'password_hash': argon2id.str(password.encode(), opslimit=argon2id.OPSLIMIT_MODERATE, memlimit=argon2id.MEMLIMIT_MODERATE).decode()})


def obtain_public_certificate(root, domain, email):
    """On issuance failure callers keep their original pinned local certificate."""
    if not shutil.which('certbot'):
        subprocess.run(['apt-get', 'update'], check=True)
        subprocess.run(['apt-get', 'install', '-y', 'certbot', 'openssl'], check=True)
    subprocess.run(['certbot', 'certonly', '--standalone', '--non-interactive', '--agree-tos', '--email', email,
                    '--cert-name', 'mehrchat', '--reuse-key', '--key-type', 'ecdsa', '-d', domain], check=True)
    issued = Path('/etc/letsencrypt/live/mehrchat')
    # Verify the issued pair before replacing the working fallback. Restore on any failure.
    server_context(issued/'fullchain.pem', issued/'privkey.pem')
    previous_cert = (root/'tls-cert.pem').read_bytes()
    previous_key = (root/'tls-key.pem').read_bytes()
    try:
        shutil.copyfile(issued/'fullchain.pem', root/'tls-cert.pem')
        shutil.copyfile(issued/'privkey.pem', root/'tls-key.pem')
        os.chmod(root/'tls-key.pem', 0o600)
    except OSError:
        (root/'tls-cert.pem').write_bytes(previous_cert)
        (root/'tls-key.pem').write_bytes(previous_key)
        os.chmod(root/'tls-key.pem', 0o600)
        raise
    # Renewals must preserve the public key pinned into distributed clients.
    target = shlex.quote(str(root))
    hook = Path('/etc/letsencrypt/renewal-hooks/deploy/mehrchat')
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text('''#!/bin/sh
set -eu
[ "$RENEWED_LINEAGE" = /etc/letsencrypt/live/mehrchat ] || exit 0
target=''' + target + '''
old=$(openssl x509 -in "$target/tls-cert.pem" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum)
new=$(openssl x509 -in "$RENEWED_LINEAGE/fullchain.pem" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum)
[ "$old" = "$new" ] || { echo 'TLS key changed: rebuild trusted clients before rotation' >&2; exit 1; }
install -o mehrchat -g mehrchat -m 644 "$RENEWED_LINEAGE/fullchain.pem" "$target/tls-cert.pem"
install -o mehrchat -g mehrchat -m 600 "$RENEWED_LINEAGE/privkey.pem" "$target/tls-key.pem"
systemctl restart mehr-relay
''')
    hook.chmod(0o750)


def configure(directory):
    from .server import Relay
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    print('\nMehrChat server setup — TLS is always enabled by this wizard.\n')
    if not (root/'admin-account.json').exists() or yes('Replace existing admin credentials?'):
        username = input('Admin username: ').strip()
        password = getpass.getpass('Admin password (at least 12 characters): ')
        if password != getpass.getpass('Repeat password: '):
            raise ValueError('Passwords do not match')
        save_admin(root, username, password)
    detected = detected_address()
    print('Detected local network IP:', detected, '(behind NAT, supply the public/server-reachable IP)')
    host = input('Client-reachable server IP [' + detected + ']: ').strip() or detected
    ipaddress.ip_address(host)
    if not yes('Confirm server IP: ' + host + '?', True):
        raise ValueError('Setup cancelled before listener configuration')
    domain = input('Optional domain (blank to use IP): ').strip().lower()
    if domain:
        if len(domain)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.')):
            raise ValueError('Invalid domain')
        print('Point the domain A/AAAA records to this server before requesting a public certificate.')
        host = domain
    port = int(input('TLS listener port [8787]: ').strip() or 8787)
    if not 1 <= port <= 65535 or port == 8788:
        raise ValueError('Invalid listener port; 8788 is reserved for loopback administration')
    ensure_certificate(root, host)
    public = False
    if domain and yes('Request a public certificate automatically (requires reachable TCP 80 and DNS)?'):
        email = input('Certificate renewal email: ').strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email): raise ValueError('Invalid email')
        try:
            obtain_public_certificate(root, domain, email)
            public = True
        except (OSError, subprocess.CalledProcessError):
            print('Public certificate unavailable. Continuing with authenticated, pinned local TLS.')
    cert = x509.load_pem_x509_certificate((root/'tls-cert.pem').read_bytes())
    tls_pin = public_key_pin(cert.public_bytes(serialization.Encoding.DER))
    relay = Relay(root)
    pin = relay.pin
    relay.db.close()
    config = {'host':host, 'port':port, 'tls': {'cert': str(root/'tls-cert.pem'), 'key': str(root/'tls-key.pem')}, 'public_certificate': public}
    write_json(root/'deployment.json', config)
    profile = validate_profile({'v':1, 'locked':True, 'relay':{'host':host, 'port':port, 'pin':pin, 'transport':'tls-noise', 'tls_pin':tls_pin}})
    write_json(root/'client-profile.json', profile)
    print('TLS + Noise configured. Public client profile:', root/'client-profile.json')
    print('The public profile contains endpoint/public keys only. Keep all other server files private.')
