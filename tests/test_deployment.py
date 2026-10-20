import asyncio
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from mehrchat.connection import probe, validate_profile
from mehrchat.crypto import create_identity, public_card, enc
from mehrchat.deployment import local_certificate, save_admin, verify_admin
from mehrchat.server import Relay
from mehrchat.wire import connect


class Credentials(unittest.TestCase):
    def test_password_hash_and_username_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            save_admin(directory, 'operator', 'long test password 123')
            raw = (Path(directory) / 'admin-credentials.json').read_text()
            self.assertNotIn('long test password', raw)
            self.assertTrue(verify_admin(directory, 'operator', 'long test password 123'))
            self.assertFalse(verify_admin(directory, 'other', 'long test password 123'))
            self.assertFalse(verify_admin(directory, 'operator', 'wrong'))

    def test_profile_allowlist_excludes_private_data(self):
        profile = validate_profile(dict(host='localhost', port=8787, pin=enc(bytes(32)),
                                        transport='tls', admin_password='secret', box_secret='private'))
        self.assertNotIn('admin_password', profile)
        self.assertNotIn('box_secret', profile)
        for change in ({'transport': 'http'}, {'port': 0}, {'host': 'bad/host'}, {'pin': ''}, {'ca': '-----BEGIN PRIVATE KEY-----'}):
            with self.assertRaises((ValueError, TypeError)):
                validate_profile(dict(profile, **change))


class TLSDeployment(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ca = local_certificate(self.root / 'tls', ['localhost', '127.0.0.1'])
        self.relay = Relay(self.root / 'data')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.root / 'tls/server.pem', self.root / 'tls/server-key.pem')
        self.server = await asyncio.start_server(self.relay.handle, '127.0.0.1', 0, ssl=context)
        self.profile = dict(host='127.0.0.1', port=self.server.sockets[0].getsockname()[1],
                            pin=self.relay.pin, transport='tls', ca=self.ca)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(.05)
        self.relay.db.close()
        self.tmp.cleanup()

    async def test_probe_verifies_tls_noise_without_registering_user(self):
        result = await probe(self.profile)
        self.assertTrue(result['ok'])
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    async def test_full_authenticated_protocol_over_tls(self):
        identity = create_identity('tls_test', 'TLS Test')
        channel = await connect(self.profile['host'], self.profile['port'], self.relay.pin,
                                identity, public_card(identity), transport='tls', ca=self.ca)
        try:
            await channel.send({'op': 'settings'})
            self.assertIn('files_enabled', await channel.recv())
        finally:
            await channel.close()

    async def test_missing_ca_rejected_without_downgrade(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            await probe(dict(self.profile, ca=''))

    async def test_wrong_hostname_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            await probe(dict(self.profile, host='wrong.example'), connect_host='127.0.0.1')

    async def test_wrong_noise_key_rejected_even_with_valid_tls(self):
        with self.assertRaises(Exception):
            await probe(dict(self.profile, pin=public_card(create_identity('wrong', 'Wrong'))['body']['box']))

    async def test_private_ca_survives_leaf_renewal(self):
        first = (self.root / 'tls/server.pem').read_bytes()
        self.assertEqual(self.ca, local_certificate(self.root / 'tls', ['localhost', '127.0.0.1']))
        self.assertNotEqual(first, (self.root / 'tls/server.pem').read_bytes())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.root / 'tls/server.pem', self.root / 'tls/server-key.pem')
        self.server.close()
        await self.server.wait_closed()
        self.server = await asyncio.start_server(self.relay.handle, '127.0.0.1', 0, ssl=context)
        self.profile['port'] = self.server.sockets[0].getsockname()[1]
        await probe(self.profile)
