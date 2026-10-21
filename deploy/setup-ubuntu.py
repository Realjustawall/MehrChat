#!/usr/bin/env python3
"""Interactive Ubuntu deployment; invoke through install-ubuntu.sh."""
import argparse
import asyncio
import getpass
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cryptography import x509
from mehrchat.deployment import local_certificate, save_admin
from mehrchat.server import Relay
from mehrchat.connection import probe

DATA = Path('/var/lib/mehrchat')
TLS = DATA / 'tls'
CONFIG = DATA / 'deployment.json'


def run(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def yes(prompt, default=False):
    return input(prompt + (' [Y/n] ' if default else ' [y/N] ')).strip().lower() in (('y', 'yes', '') if default else ('y', 'yes'))


def own(path):
    user = pwd.getpwnam('mehrchat')
    os.chown(path, user.pw_uid, user.pw_gid)


def renew(config):
    if config.get('public_tls'):
        subprocess.run(['certbot', 'renew', '--quiet'], check=False)
        live = Path('/etc/letsencrypt/live') / config['domain']
        try:
            cert = x509.load_pem_x509_certificate((live / 'cert.pem').read_bytes())
            if cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=1):
                shutil.copyfile(live / 'fullchain.pem', TLS / 'server.pem')
                shutil.copyfile(live / 'privkey.pem', TLS / 'server-key.pem')
            else:
                raise ValueError('Public certificate expired')
        except (OSError, ValueError):
            local_certificate(TLS, config['hosts'])
    else:
        cert = x509.load_pem_x509_certificate((TLS / 'server.pem').read_bytes())
        if cert.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=30):
            local_certificate(TLS, config['hosts'])
    for path in TLS.iterdir():
        path.chmod(0o600)
        own(path)
    own(TLS)
    run('systemctl', 'restart', 'mehr-relay')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--renew', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        sys.exit('Run with sudo.')
    if args.renew:
        renew(json.loads(CONFIG.read_text()))
        return
    print('MehrChat · Ubuntu secure setup')
    if CONFIG.exists() and not yes('An installation exists. Reconfigure it?'):
        return
    admin = input('Admin username: ').strip()
    password = getpass.getpass('Admin password (minimum 14 characters): ')
    if password != getpass.getpass('Repeat password: '):
        sys.exit('Passwords differ; nothing was changed.')
    if not admin or len(admin) > 64 or len(password) < 14:
        sys.exit('Invalid administrator credentials; nothing was changed.')
    # The default is local interface discovery, never an untrusted remote HTTP IP service.
    try:
        detected = socket.gethostbyname(socket.gethostname())
    except OSError:
        detected = '127.0.0.1'
    try:
        addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
        detected = next(info['local'] for dev in addresses for info in dev.get('addr_info', []) if info.get('scope') == 'global')
    except (OSError, ValueError, StopIteration, KeyError):
        pass
    while True:
        host = input(f'Server public/reachable IP [{detected}]: ').strip() or detected
        try:
            ipaddress.ip_address(host)
        except ValueError:
            print('Enter an IPv4 or IPv6 address.')
            continue
        if yes(f'Confirm server IP: {host}?', True):
            break
    domain = input('Optional domain (Enter to skip): ').strip().lower()
    if domain and not re.fullmatch(r'(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
        sys.exit('Invalid domain.')
    while True:
        raw_port = input('TLS relay port [8787]: ').strip() or '8787'
        if raw_port.isascii() and raw_port.isdigit() and 1 <= int(raw_port) <= 65535 and int(raw_port) != 8788:
            port = int(raw_port)
            break
        print('Enter a port from 1 to 65535; 8788 is reserved for loopback administration.')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    save_admin(DATA, admin, password)
    password = None
    relay = Relay(DATA)
    pin = relay.pin
    relay.db.close()
    listen_host = '::' if ipaddress.ip_address(host).version == 6 else '0.0.0.0'
    loopback_host = '::1' if ipaddress.ip_address(host).version == 6 else '127.0.0.1'
    hosts = [host] + ([domain] if domain else [])
    ca = local_certificate(TLS, hosts)
    public = False
    if domain and yes('Request a public Let’s Encrypt certificate? DNS must point here and TCP 80 must be open.'):
        email = input('Certificate renewal email: ').strip()
        run('apt-get', 'install', '-y', 'certbot')
        result = subprocess.run(['certbot', 'certonly', '--standalone', '--non-interactive', '--agree-tos', '--email', email, '-d', domain])
        public = result.returncode == 0
        if not public:
            print('Public certificate request failed. Verified TLS with the private CA remains enabled.')
    config = dict(hosts=hosts, domain=domain, port=port, public_tls=public)
    CONFIG.write_text(json.dumps(config))
    CONFIG.chmod(0o600)
    # Restrict all state, including credentials and private CA, to the service account.
    for path in DATA.rglob('*'):
        own(path)
        path.chmod(0o700 if path.is_dir() else 0o600)
    own(DATA)
    override = Path('/etc/systemd/system/mehr-relay.service.d')
    override.mkdir(parents=True, exist_ok=True)
    (override / 'tls.conf').write_text('[Service]\nExecStart=\nExecStart=/opt/mehrchat/venv/bin/python -m mehrchat.server --data /var/lib/mehrchat --host ' + listen_host + ' --port ' + str(port) + ' --tls-cert /var/lib/mehrchat/tls/server.pem --tls-key /var/lib/mehrchat/tls/server-key.pem\n')
    Path('/etc/systemd/system/mehr-tls-renew.service').write_text('[Unit]\nDescription=Renew MehrChat TLS with private CA fallback\n[Service]\nType=oneshot\nExecStart=/opt/mehrchat/venv/bin/python /opt/mehrchat/deploy/setup-ubuntu.py --renew\nWorkingDirectory=/opt/mehrchat\nUMask=0077\n')
    Path('/etc/systemd/system/mehr-tls-renew.timer').write_text('[Unit]\nDescription=Maintain MehrChat TLS certificates\n[Timer]\nOnCalendar=daily\nRandomizedDelaySec=3600\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
    run('systemctl', 'daemon-reload')
    renew(config)
    run('systemctl', 'enable', '--now', 'mehr-relay', 'mehr-tls-renew.timer')
    profile = dict(host=domain or host, port=port, pin=pin, transport='tls', ca=ca)
    # Test the real listener locally with the IP SAN; endpoint reachability is tested by clients.
    for attempt in range(20):
        try:
            asyncio.run(probe(profile, connect_host=loopback_host))
            break
        except (OSError, ValueError):
            import time
            time.sleep(.5)
    else:
        sys.exit('Service did not pass TLS/Noise readiness check. Inspect journalctl -u mehr-relay.')
    profile_path = DATA / 'client-profile.json'
    profile_path.write_text(json.dumps(profile, indent=2))
    profile_path.chmod(0o644)
    own(profile_path)
    print(f'TLS + Noise enabled on TCP {port}. Open this port in your host/provider firewall.\nPublic connection profile: {profile_path}\nAdmin: http://127.0.0.1:8788 (use an SSH tunnel).')
    print('Only the public profile goes into client builds; private keys and admin credentials stay here.')
    build_clients(profile_path)


def build_clients(profile_path):
    command = ['/opt/mehrchat/venv/bin/python', '/opt/mehrchat/scripts/request-client-build.py',
               str(profile_path), '--output', str(DATA / 'dedicated-clients')]
    if yes('Build and download dedicated Windows and Android clients now?', True):
        if not shutil.which('gh'):
            print('GitHub CLI is missing. Install gh, authenticate, and run the command below.')
        else:
            authenticated = subprocess.run(['gh', 'auth', 'status'], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL).returncode == 0
            if not authenticated:
                print('GitHub Actions needs your account. Authenticate on this server using the displayed device code.')
                authenticated = subprocess.run(['gh', 'auth', 'login', '--hostname', 'github.com',
                                                 '--git-protocol', 'https', '--web']).returncode == 0
            if authenticated:
                result = subprocess.run(command)
                if result.returncode == 0:
                    print('Dedicated clients downloaded to ' + str(DATA / 'dedicated-clients'))
                    return
                print('Client build did not finish successfully. The verified relay remains running.')
            else:
                print('GitHub authentication was not completed. The verified relay remains running.')
        import shlex
        print('Resume client build with: ' + shlex.join(command))


if __name__ == '__main__':
    main()
