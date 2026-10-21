"""Server-local credential and certificate provisioning. No client secrets here."""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def save_admin(root, username, password):
    if not username.strip() or len(username) > 64 or len(password) < 14:
        raise ValueError("Admin username required; password must be at least 14 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    path = Path(root) / "admin-credentials.json"
    path.write_text(json.dumps(dict(username=username, salt=salt.hex(), digest=digest.hex())))
    path.chmod(0o600)


def verify_admin(root, username, password):
    path = Path(root) / "admin-credentials.json"
    if not path.exists():
        return False
    entry = json.loads(path.read_text())
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(entry["salt"]), n=16384, r=8, p=1)
    return hmac.compare_digest(entry["username"].encode(), username.encode()) & hmac.compare_digest(entry["digest"], digest.hex())


def local_certificate(root, hosts):
    """Persistent private CA, renewable leaf, explicit IP/DNS SAN verification."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(timezone.utc)
    def write_key(path, key):
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        path.chmod(0o600)
    ca_path, key_path = root / "ca.pem", root / "ca-key.pem"
    if ca_path.exists() != key_path.exists():
        raise ValueError("Incomplete CA; restore its certificate and key before renewing")
    if ca_path.exists():
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        key = serialization.load_pem_private_key(key_path.read_bytes(), None)
        public_format = serialization.PublicFormat.SubjectPublicKeyInfo
        if key.public_key().public_bytes(serialization.Encoding.DER, public_format) != ca.public_key().public_bytes(serialization.Encoding.DER, public_format):
            raise ValueError("Private CA key does not match its certificate")
        missing = []
        for extension in (x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                          x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key())):
            try:
                ca.extensions.get_extension_for_class(type(extension))
            except x509.ExtensionNotFound:
                missing.append(extension)
        if missing:
            (root / "ca-legacy.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
            builder = (x509.CertificateBuilder().subject_name(ca.subject).issuer_name(ca.issuer)
                       .public_key(ca.public_key()).serial_number(ca.serial_number)
                       .not_valid_before(ca.not_valid_before_utc).not_valid_after(ca.not_valid_after_utc))
            for extension in ca.extensions:
                builder = builder.add_extension(extension.value, extension.critical)
            for extension in missing:
                builder = builder.add_extension(extension, critical=False)
            ca = builder.sign(key, hashes.SHA256())
            ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
            print("Updated legacy CA certificate identifiers; redistribute the exported public profile to strict TLS clients.")
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MehrChat private deployment CA")])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
              .not_valid_after(now + timedelta(days=3650))
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
              .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
              .sign(key, hashes.SHA256()))
        write_key(key_path, key)
        ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    names = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
            .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(min(now + timedelta(days=365), ca.not_valid_after_utc))
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    write_key(root / "server-key.pem", leaf_key)
    (root / "server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    return ca_path.read_text()
