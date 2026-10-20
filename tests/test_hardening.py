"""Privacy-policy regressions: real SOCKS/Noise sockets and bounded abuse state."""
import ast
import asyncio
import copy
import json
import struct
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.request import urlopen

from test_security import MemoryVault, clients
from mehrchat.client import Engine
from mehrchat.crypto import signed
from mehrchat.i18n import EN, language, load_language, save_language, set_language, tr
from mehrchat.limits import AdmissionLimiter
from mehrchat.server import Relay
from mehrchat.wire import Channel, connect, open_transport, validate_proxy


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        set_language('fa')

    def test_every_persian_application_string_has_a_translation(self):
        import re
        for path in Path('mehrchat').glob('*.py'):
            if path.name in ('i18n.py', 'smoke.py', 'server.py'):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search('[\u0600-\u06ff]', node.value):
                    if node.value == 'فارسی':  # Language names remain recognizable in either locale.
                        continue
                    self.assertIn(node.value, EN, (path, node.lineno, node.value))

    def test_language_is_portable_and_does_not_translate_unknown_user_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'language.json'
            save_language(path, 'en')
            self.assertEqual(tr('ذخیره'), 'Save')
            self.assertEqual(tr('سلام از علی'), 'سلام از علی')
            set_language('fa')
            load_language(path)
            self.assertEqual(language(), 'en')
            path.write_text('{bad')
            load_language(path)
            self.assertEqual(language(), 'fa')
            with self.assertRaises(ValueError):
                save_language(path, 'other')


class PolicyTests(unittest.TestCase):
    def test_proxy_settings_cannot_select_a_remote_host_or_invalid_port(self):
        for proxy in ({}, {'host':'localhost','port':9050}, {'host':'example.org','port':9050},
                      {'host':'192.0.2.1','port':9050}, {'host':'127.0.0.1','port':True},
                      {'host':'127.0.0.1','port':0}, {'host':'::1','port':65536}):
            with self.assertRaises(ValueError):
                validate_proxy(proxy)
        self.assertEqual(validate_proxy({'host':'::1','port':9050})['host'], '::1')

    def test_privacy_policy_is_saved_atomically_and_retained_after_restart(self):
        vault = MemoryVault('alice')
        engine = Engine(vault)
        proxy = {'host':'127.0.0.1','port':9050}
        engine.configure_privacy(proxy, 30)
        with patch.object(vault, 'save', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                engine.configure_privacy(None, 300)
        restored = Engine(vault)
        self.assertEqual(restored.d['proxy'], proxy)
        self.assertEqual(restored.d['auto_lock'], 30)

    def test_admission_limits_survive_retries_and_have_bounded_memory(self):
        limiter = AdmissionLimiter(rate=1, burst=2, capacity=2, idle=10)
        self.assertTrue(limiter.allow('one', 0))
        self.assertTrue(limiter.allow('one', 0))
        self.assertFalse(limiter.allow('one', 0))
        self.assertTrue(limiter.allow('two', 0))
        self.assertFalse(limiter.allow('three', 0))
        self.assertFalse(limiter.allow('one', 0))
        self.assertTrue(limiter.allow('one', 1))
        self.assertTrue(limiter.allow('three', 20))
        self.assertLessEqual(len(limiter.entries), 2)

    def test_android_screen_protection_is_acknowledged_and_fails_closed(self):
        from mehrchat.privacy import protect_android_screen
        window = SimpleNamespace(flags=0)
        window.addFlags = lambda flag: setattr(window, 'flags', window.flags | flag)
        window.getAttributes = lambda: window
        window.setHideOverlayWindows = lambda enabled: None
        classes = {
            'org.kivy.android.PythonActivity': SimpleNamespace(mActivity=SimpleNamespace(getWindow=lambda:window)),
            'android.view.WindowManager$LayoutParams': SimpleNamespace(FLAG_SECURE=8192),
            'android.os.Build$VERSION': SimpleNamespace(SDK_INT=35),
        }
        modules = {'android.runnable': SimpleNamespace(run_on_ui_thread=lambda fn:fn),
                   'jnius': SimpleNamespace(autoclass=classes.__getitem__)}
        with patch.dict('sys.modules', modules):
            results = []
            protect_android_screen(results.append)
            self.assertEqual(results, [True])
            window.setHideOverlayWindows = lambda enabled: (_ for _ in ()).throw(RuntimeError())
            protect_android_screen(results.append)
            self.assertEqual(results, [True, False])

    def test_registration_and_retraction_quotas_preserve_existing_users_and_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = Relay(directory)
            try:
                alice, bob = Engine(MemoryVault('alice')), Engine(MemoryVault('bobby'))
                relay.register(alice.card)
                with patch('mehrchat.server.MAX_USERS', 1):
                    relay.register(alice.card)
                    with self.assertRaises(ValueError):
                        relay.register(bob.card)
                now = int(time.time())
                def request(eid):
                    cap = signed(alice.identity, dict(context='MehrChat-retract-v2',id=eid,sender=alice.me,to=bob.me,expires=now+60))
                    return signed(alice.identity, dict(v=2,kind='retract',sender=alice.me,to=alice.me,expires=now+90,proofs=[{'card':alice.card,'cap':cap}]))
                with patch('mehrchat.server.MAX_ROUTE_RETRACTIONS', 1):
                    relay.retract(alice.card, request('a'*32))
                    relay.retract(alice.card, request('a'*32))
                    with self.assertRaises(ValueError):
                        relay.retract(alice.card, request('b'*32))
                    self.assertEqual(relay.db.execute('SELECT id FROM retractions').fetchall(), [('a'*32,)])
            finally:
                relay.db.close()

    def test_admin_page_is_bilingual_and_sets_privacy_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            relay = Relay(directory)
            admin = relay.start_admin(0)
            try:
                root = 'http://127.0.0.1:%d/' % admin.server_address[1]
                with urlopen(root+'?lang=en') as response:
                    self.assertIn(b'lang="en" dir="ltr"', response.read())
                    self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
                with urlopen(root+'?lang=fa') as response:
                    self.assertIn('تنظیمات سرور', response.read().decode())
            finally:
                admin.shutdown()
                admin.server_close()
                relay.db.close()


class ProxyNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.relay = Relay(self.temp.name)
        self.server = await asyncio.start_server(self.relay.handle, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.tasks = set()
        self.targets = []
        self.observed = bytearray()
        self.reject = False
        self.proxy_server = await asyncio.start_server(self.proxy_peer, '127.0.0.1', 0)
        self.proxy = {'host':'127.0.0.1','port':self.proxy_server.sockets[0].getsockname()[1]}
        self.alice = Engine(MemoryVault('alice'))
        self.channels = []

    async def proxy_peer(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        try:
            self.assertEqual(await reader.readexactly(3), b'\x05\x01\x00')
            if self.reject:
                writer.write(b'\x05\xff')
                await writer.drain()
                return
            writer.write(b'\x05\x00')
            await writer.drain()
            header = await reader.readexactly(4)
            self.assertEqual(header[:3], b'\x05\x01\x00')
            kind = header[3]
            size = (await reader.readexactly(1))[0] if kind == 3 else 4 if kind == 1 else 16
            address = await reader.readexactly(size)
            port = struct.unpack('!H', await reader.readexactly(2))[0]
            self.targets.append((kind, address, port))
            remote, upstream = await asyncio.open_connection('127.0.0.1', self.port)
            writer.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
            await writer.drain()
            async def pipe(source, destination):
                try:
                    while raw := await source.read(65536):
                        self.observed.extend(raw)
                        destination.write(raw)
                        await destination.drain()
                finally:
                    destination.close()
            await asyncio.gather(pipe(reader, upstream), pipe(remote, writer))
        finally:
            writer.close()
            if upstream:
                upstream.close()
            self.tasks.discard(task)

    async def asyncTearDown(self):
        for channel in self.channels:
            await channel.close()
        self.proxy_server.close()
        self.server.close()
        await self.proxy_server.wait_closed()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await asyncio.sleep(0.05)
        self.relay.db.close()
        self.temp.cleanup()

    async def test_pinned_noise_authentication_through_proxy_without_destination_dns(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('Destination DNS leaked')):
            channel = await connect('relay.test.invalid', self.port, self.relay.pin,
                                    self.alice.identity, self.alice.card, proxy=self.proxy)
            self.channels.append(channel)
            await channel.send({'op':'settings'})
            self.assertTrue((await channel.recv())['ok'])
        self.assertEqual(self.targets, [(3,b'relay.test.invalid',self.port)])

    async def test_proxy_failure_never_falls_back_to_direct(self):
        self.reject = True
        with self.assertRaises(ValueError):
            await connect('127.0.0.1', self.port, self.relay.pin,
                          self.alice.identity, self.alice.card, proxy=self.proxy)
        self.assertFalse(self.relay.active)
        self.assertFalse(self.targets)

    async def test_e2ee_message_roundtrip_through_socks_proxy(self):
        alice, bob, _ = clients()
        channels = []
        for engine in (alice, bob):
            channel = await connect('relay.test.invalid', self.port, self.relay.pin,
                                    engine.identity, engine.card, proxy=self.proxy)
            self.channels.append(channel)
            channels.append(channel)
        chat = alice.dm_id(bob.me)
        secret = 'private-socks-message-unique-731'
        alice.send(chat, secret)
        await channels[0].send({'op':'put', 'item':alice.d['outbox'][-1]['item']})
        self.assertTrue((await channels[0].recv())['ok'])
        await channels[1].send({'op':'fetch'})
        bob.ingest((await channels[1].recv())['item'])
        self.assertEqual(bob.d['messages'][chat][-1]['text'], secret)
        self.assertNotIn(secret.encode(), self.observed)
        row = self.relay.db.execute('SELECT data FROM queue').fetchone()[0]
        self.assertNotIn(secret.encode(), row)

    async def test_onion_is_never_resolved_without_proxy(self):
        with patch('mehrchat.wire.asyncio.open_connection', new_callable=AsyncMock) as opener:
            with self.assertRaises(ValueError):
                await open_transport('example.onion', self.port)
            opener.assert_not_called()

    async def test_proxy_does_not_bypass_wrong_server_pin(self):
        from mehrchat.crypto import enc
        with self.assertRaises(Exception):
            await connect('relay.test.invalid', self.port, enc(b'x'*32),
                          self.alice.identity, self.alice.card, proxy=self.proxy)
        self.assertFalse(self.relay.active)

    async def test_transport_padding_preserves_legacy_json_and_bucket_size(self):
        class Noise:
            def encrypt(self, raw):
                return raw
        class Writer:
            def __init__(self): self.raw = bytearray()
            def write(self, raw): self.raw.extend(raw)
            async def drain(self): pass
        writer = Writer()
        channel = Channel(None, writer, Noise())
        await channel.send({'small':'private'})
        raw = bytes(writer.raw)
        self.assertEqual(struct.unpack('!I',raw[4:8])[0], 1024)
        self.assertEqual(json.loads(raw[12:]), {'small':'private'})

    async def test_segmented_record_has_a_whole_record_deadline(self):
        class Noise:
            def decrypt(self, raw): return raw
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack('!II', 4, 100))
        async def trickle():
            for _ in range(100):
                await asyncio.sleep(0.01)
                reader.feed_data(struct.pack('!I', 1) + b' ')
        task = asyncio.create_task(trickle())
        try:
            with patch('mehrchat.wire.RECORD_TIMEOUT', 0.035):
                with self.assertRaises(asyncio.TimeoutError):
                    await Channel(reader, None, Noise()).recv()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
