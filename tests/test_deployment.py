import asyncio
import copy
import importlib.util
import json
import os
import ssl
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mehrchat.crypto import create_identity, public_card
from mehrchat.deployment import validate_profile, validate_relay, write_json
from mehrchat.server import Relay
from mehrchat.setup import configure, save_admin
from mehrchat.tls import ensure_certificate, server_context
from mehrchat.wire import connect, preflight
from mehrchat.client import Engine
from test_security import MemoryVault


class TLSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.relay=Relay(self.root)
        self.pin=ensure_certificate(self.root,'localhost')
        self.server=await asyncio.start_server(self.relay.handle,'127.0.0.1',0,ssl=server_context(self.root/'tls-cert.pem',self.root/'tls-key.pem'),ssl_handshake_timeout=2)
        self.profile={'host':'127.0.0.1','port':self.server.sockets[0].getsockname()[1],'pin':self.relay.pin,'transport':'tls-noise','tls_pin':self.pin}

    async def asyncTearDown(self):
        self.server.close();await self.server.wait_closed()
        await asyncio.sleep(0.05)
        self.relay.db.close();self.tmp.cleanup()

    async def test_tls_noise_probe_discovers_noise_pin_without_registering_identity(self):
        value=dict(self.profile,pin='')
        resolved,info=await preflight(value)
        self.assertEqual(resolved['pin'],self.relay.pin)
        self.assertTrue(info['tls'])
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM users').fetchone()[0],0)
        self.assertFalse(self.relay.live_cards)

    async def test_real_tls_noise_login_and_server_reply(self):
        ident=create_identity('alice','Alice')
        c=await connect(self.profile['host'],self.profile['port'],self.relay.pin,ident,public_card(ident),transport='tls-noise',tls_pin=self.pin)
        try:
            await c.send({'op':'settings'})
            self.assertTrue((await c.recv())['ok'])
            self.assertIsNotNone(c.writer.get_extra_info('ssl_object'))
        finally:await c.close()

    async def test_wrong_tls_pin_fails_before_registration(self):
        with self.assertRaises(ValueError):await preflight(dict(self.profile,tls_pin='0'*64))
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM users').fetchone()[0],0)

    async def test_self_signed_without_trusted_pin_is_rejected(self):
        with self.assertRaises(ssl.SSLError):await preflight(dict(self.profile,tls_pin=''))

    async def test_tls_does_not_bypass_wrong_noise_key(self):
        other=public_card(create_identity('other','Other'))['body']['box']
        with self.assertRaises(Exception):await preflight(dict(self.profile,pin=other))
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM users').fetchone()[0],0)

    async def test_tls_noise_preflight_through_socks_keeps_destination_dns_remote(self):
        import struct
        tasks=set(); destinations=[]
        async def proxy(reader,writer):
            tasks.add(asyncio.current_task())
            upstream=None
            try:
                self.assertEqual(await reader.readexactly(3),b'\x05\x01\x00')
                writer.write(b'\x05\x00');await writer.drain()
                self.assertEqual(await reader.readexactly(4),b'\x05\x01\x00\x03')
                length=(await reader.readexactly(1))[0]
                destinations.append(await reader.readexactly(length))
                await reader.readexactly(2)
                remote,upstream=await asyncio.open_connection('127.0.0.1',self.profile['port'])
                writer.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00');await writer.drain()
                async def pipe(source,dest):
                    try:
                        while raw:=await source.read(65536):dest.write(raw);await dest.drain()
                    finally:dest.close()
                await asyncio.gather(pipe(reader,upstream),pipe(remote,writer))
            finally:
                writer.close()
                if upstream:upstream.close()
                tasks.discard(asyncio.current_task())
        listener=await asyncio.start_server(proxy,'127.0.0.1',0)
        try:
            resolved,info=await preflight(dict(self.profile,host='relay.invalid'),proxy={'host':'127.0.0.1','port':listener.sockets[0].getsockname()[1]})
            self.assertTrue(info['tls'])
            self.assertEqual(destinations,[b'relay.invalid'])
        finally:
            listener.close();await listener.wait_closed()
            for task in list(tasks):task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)

    def test_reinstallation_retains_tls_private_identity(self):
        before=(self.root/'tls-key.pem').read_bytes()
        self.assertEqual(self.pin,ensure_certificate(self.root,'localhost'))
        self.assertEqual(before,(self.root/'tls-key.pem').read_bytes())
        if os.name!='nt':self.assertEqual((self.root/'tls-key.pem').stat().st_mode&0o777,0o600)


class DeploymentTests(unittest.TestCase):
    def test_public_profile_excludes_credentials_and_private_keys(self):
        r={'host':'example.org','port':443,'pin':public_card(create_identity('alice','A'))['body']['box'],'transport':'tls-noise','tls_pin':'a'*64}
        profile={'v':1,'locked':True,'relay':r}
        self.assertEqual(profile,validate_profile(profile))
        for field in ('password','admin_token','box_secret'):
            with self.assertRaises(ValueError):validate_profile(dict(profile,**{field:'secret'}))
            with self.assertRaises(ValueError):validate_profile(dict(profile,relay=dict(r,**{field:'secret'})))
        with self.assertRaises(ValueError):validate_profile(dict(profile,relay=dict(r,transport='noise',tls_pin='')))

    def test_locked_engine_refuses_endpoint_changes(self):
        r={'host':'example.org','port':443,'pin':public_card(create_identity('alice','A'))['body']['box'],'transport':'tls-noise','tls_pin':'a'*64}
        engine=Engine(MemoryVault('bobby'),locked_relay=r)
        before=copy.deepcopy(engine.d)
        with self.assertRaises(ValueError):engine.configure_relays([dict(r,host='evil.example')])
        self.assertEqual(before,engine.d)

    def test_admin_credentials_hash_password_and_disable_legacy_token(self):
        with tempfile.TemporaryDirectory() as directory:
            save_admin(directory,'admin','a long test password')
            r=Relay(directory)
            try:
                self.assertNotIn('a long test password',r.admin_credentials.read_text())
                self.assertFalse(r.authenticate_admin({'token':[r.admin_token]}))
                self.assertFalse(r.authenticate_admin({'username':['admin'],'password':['wrong']}))
                self.assertTrue(r.authenticate_admin({'username':['admin'],'password':['a long test password']}))
            finally:r.db.close()

    def test_failed_acme_keeps_working_pinned_tls_and_safe_public_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            answers=['admin','127.0.0.1','','example.org','','y','admin@example.org']
            with patch('builtins.input',side_effect=answers),patch('getpass.getpass',return_value='a long admin password'),patch('mehrchat.setup.detected_address',return_value='127.0.0.1'),patch('mehrchat.setup.obtain_public_certificate',side_effect=subprocess.CalledProcessError(1,'certbot')):
                configure(directory)
            root=Path(directory)
            cfg=json.loads((root/'deployment.json').read_text())
            self.assertFalse(cfg['public_certificate'])
            server_context(cfg['tls']['cert'],cfg['tls']['key'])
            profile=validate_profile(json.loads((root/'client-profile.json').read_text()))
            self.assertEqual(profile['relay']['transport'],'tls-noise')
            self.assertEqual(profile['relay']['host'],'example.org')
            self.assertEqual(profile['relay']['tls_pin'],ensure_certificate(root,'example.org'))
            self.assertNotIn('admin password',(root/'client-profile.json').read_text())

    def test_local_signing_helper_profile_rejects_private_fields(self):
        spec=importlib.util.spec_from_file_location('deployment_builder',Path('scripts/build-personalized.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'profile.json'
            write_json(path,{'v':1,'locked':True,'relay':{},'password':'never upload'})
            with self.assertRaises(ValueError):module.public_profile(path)
