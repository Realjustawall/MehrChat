"""TLS in addition to Noise. Pin public keys, so certificate renewal is safe."""
import datetime
import hashlib
import ipaddress
import ssl
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def public_key_pin(der):
    cert = x509.load_der_x509_certificate(der)
    raw = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(raw).hexdigest()


def client_context(pin=None):
    context = ssl.create_default_context()
    import certifi
    context.load_verify_locations(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if pin:
        if not isinstance(pin, str) or len(pin) != 64 or any(c not in '0123456789abcdef' for c in pin):
            raise ValueError('Invalid TLS public-key pin')
        # Authentication is performed by check_peer BEFORE any app data is sent.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def check_peer(writer, pin):
    import hmac
    session = writer.get_extra_info('ssl_object')
    if session is None:
        raise ValueError('TLS is required')
    if pin and not hmac.compare_digest(public_key_pin(session.getpeercert(binary_form=True)), pin):
        raise ValueError('TLS public-key pin mismatch')


def server_context(cert, key):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return context


def ensure_certificate(directory, host):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    certfile, keyfile = root / 'tls-cert.pem', root / 'tls-key.pem'
    if certfile.exists() != keyfile.exists():
        raise ValueError('Incomplete TLS identity; restore the missing file')
    if not certfile.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
        try:
            san = x509.IPAddress(ipaddress.ip_address(host))
        except ValueError:
            san = x509.DNSName(host.encode('idna').decode('ascii'))
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([san]), critical=False)
                .sign(key, hashes.SHA256()))
        with keyfile.open('xb') as f:
            import os
            if os.name != 'nt': os.fchmod(f.fileno(), 0o600)
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert = x509.load_pem_x509_certificate(certfile.read_bytes())
    return public_key_pin(cert.public_bytes(serialization.Encoding.DER))
