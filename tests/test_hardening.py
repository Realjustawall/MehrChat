"""Regressions for the 0.7.0 resource, privacy and decoder findings."""
import asyncio
import copy
import json
import struct
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from test_security import clients
from mehrchat.crypto import create_identity, public_card, signed, check_card, pack
from mehrchat.server import Relay
from mehrchat.wire import Channel, ReceiveBudget, connect
from mehrchat import ratchet


class CardAndDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.relay = Relay(self.tmp.name)
        self.identity = create_identity('alice', 'Alice')
        self.card = public_card(self.identity)

    def tearDown(self):
        self.relay.db.close()
        self.tmp.cleanup()

    def test_signed_padding_never_enters_directory(self):
        body = dict(self.card['body'], unexpected_padding='x' * 131072)
        with self.assertRaises(ValueError):
            self.relay.register(signed(self.identity, body))
        self.assertEqual(self.relay.db.execute('SELECT count(*) FROM users').fetchone()[0], 0)

    def test_top_level_fields_and_boolean_version_rejected(self):
        for card in [dict(self.card, padding='secret'), signed(self.identity, dict(self.card['body'], v=True))]:
            with self.assertRaises(ValueError):
                check_card(card)

    def test_directory_count_limit_still_allows_existing_profile_update(self):
        with patch('mehrchat.server.MAX_USERS', 1):
            self.relay.register(self.card)
            self.identity['name'] = 'New name'
            self.relay.register(public_card(self.identity))
            with self.assertRaises(ValueError):
                self.relay.register(public_card(create_identity('bobby', 'Bob')))

    def test_directory_bytes_and_registration_rate_are_separate_limits(self):
        with patch('mehrchat.server.MAX_DIRECTORY_BYTES', 10):
            with self.assertRaises(ValueError):
                self.relay.register(self.card)
        self.relay.registration_tokens = 0
        self.relay.registration_last = time.monotonic()
        with self.assertRaises(ValueError):
            self.relay.register(self.card)


class MessageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = clients()
        self.chat = self.a.dm_id(self.b.me)

    def payload(self):
        now = int(time.time())
        return dict(id=uuid.uuid4().hex, chat={'private': [self.a.me, self.b.me]},
                    author=self.a.me, created=now, expires=now + 3600,
                    kind='message', text='short')

    def reject(self, payload):
        packet = self.a.secure.encrypt(self.b.me, payload, payload['expires'], payload['kind'])
        before = copy.deepcopy(self.b.d)
        with self.assertRaises(ValueError):
            self.b.ingest(packet)
        self.assertEqual(self.b.d, before, 'Rejection must roll back the ratchet as well as history')

    def test_authenticated_message_padding_is_rejected(self):
        self.reject(dict(self.payload(), unexpected_padding='x' * 131072))

    def test_nested_chat_padding_is_rejected(self):
        payload = self.payload()
        payload['chat']['padding'] = 'x' * 131072
        self.reject(payload)

    def test_text_must_be_string(self):
        self.reject(dict(self.payload(), text=['x'] * 100))

    def test_history_limit_rejects_receive_without_ratchet_advance(self):
        with patch('mehrchat.client.MAX_HISTORY_BYTES', 100):
            self.reject(self.payload())

    def test_history_limit_rejects_send_without_outbox_or_ratchet_advance(self):
        before = copy.deepcopy(self.a.d)
        with patch('mehrchat.client.MAX_HISTORY_BYTES', 100):
            with self.assertRaises(ValueError):
                self.a.send(self.chat, 'new message')
        self.assertEqual(before, self.a.d)

    def test_skipped_keys_expire_and_no_longer_decrypt_delayed_message(self):
        self.a.send(self.chat, 'delayed', ttl=7 * 86400)
        first = self.a.d['outbox'][-1]['item']
        self.a.send(self.chat, 'arrives first', ttl=7 * 86400)
        self.b.ingest(self.a.d['outbox'][-1]['item'])
        state = self.b.d['sessions'][self.a.me]['state']
        self.assertTrue(state['skipped_message_keys'])
        timestamps = dict(state[ratchet.KEY_TIMES])
        self.assertEqual(timestamps, ratchet.prune_state(state)[ratchet.KEY_TIMES])
        with patch('mehrchat.ratchet.time.time', return_value=time.time() + ratchet.SKIPPED_KEY_TTL + 1):
            self.b.prune()
            self.assertFalse(self.b.d['sessions'][self.a.me]['state']['skipped_message_keys'])
            with self.assertRaises(Exception):
                self.b.ingest(first)

    def test_legacy_skipped_keys_get_one_persisted_migration_deadline(self):
        self.a.send(self.chat, 'one')
        self.a.send(self.chat, 'two')
        self.b.ingest(self.a.d['outbox'][-1]['item'])
        state = copy.deepcopy(self.b.d['sessions'][self.a.me]['state'])
        state.pop(ratchet.KEY_TIMES)
        migrated = ratchet.prune_state(state, now=1000)
        self.assertTrue(migrated['skipped_message_keys'])
        expired = ratchet.prune_state(migrated, now=1000 + ratchet.SKIPPED_KEY_TTL)
        self.assertFalse(expired['skipped_message_keys'])


class IdentityNoise:
    def decrypt(self, value):
        return value


def feed(reader, raw):
    reader.feed_data(struct.pack('!I', len(raw)) + raw)


class TransportBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_record_deadline_and_reservation_release_on_timeout(self):
        reader = asyncio.StreamReader()
        feed(reader, struct.pack('!I', 100))
        budget = ReceiveBudget(200)
        channel = Channel(reader, None, IdentityNoise(), budget)
        with patch('mehrchat.wire.RECORD_TIMEOUT', .03):
            with self.assertRaises(asyncio.TimeoutError):
                await channel.recv()
        self.assertEqual(budget.used, 0)

    async def test_tiny_segments_rejected_and_budget_released(self):
        reader = asyncio.StreamReader()
        feed(reader, struct.pack('!I', 100))
        feed(reader, b'x')
        budget = ReceiveBudget(200)
        with self.assertRaises(ValueError):
            await Channel(reader, None, IdentityNoise(), budget).recv()
        self.assertEqual(budget.used, 0)

    async def test_global_receive_budget_is_shared(self):
        reader = asyncio.StreamReader()
        feed(reader, struct.pack('!I', 100))
        budget = ReceiveBudget(150)
        budget.reserve(100)
        with self.assertRaises(ValueError):
            await Channel(reader, None, IdentityNoise(), budget).recv()
        self.assertEqual(budget.used, 100)
        budget.release(100)

    async def test_presence_not_disclosed_to_noncontact_and_strict_requests(self):
        with tempfile.TemporaryDirectory() as root:
            relay = Relay(root)
            server = await asyncio.start_server(relay.handle, '127.0.0.1', 0)
            channels = []
            try:
                for name in ('alice', 'bobby'):
                    ident = create_identity(name, name)
                    ch = await connect('127.0.0.1', server.sockets[0].getsockname()[1],
                                       relay.pin, ident, public_card(ident))
                    channels.append(ch)
                await channels[1].send({'op': 'lookup', 'username': 'alice'})
                result = await channels[1].recv()
                self.assertNotIn('online', result)
                self.assertIsNone(result['card'])
                await channels[1].send({'op': 'settings', 'padding': 'x'})
                with self.assertRaises(asyncio.IncompleteReadError):
                    await channels[1].recv()
            finally:
                for ch in channels:
                    await ch.close()
                server.close()
                await server.wait_closed()
                await asyncio.sleep(.05)
                relay.db.close()


class QRBoundaryTests(unittest.TestCase):
    def test_real_qr_decodes_inside_worker(self):
        import os
        if os.name == 'nt':
            self.skipTest('Packaged AppContainer QR roundtrip is covered by verify_media_sandbox.py')
        from mehrchat.contact_invite import invite, qr_png, decode_image
        invitation = invite(public_card(create_identity('qrtest', 'QR test')))
        self.assertEqual(decode_image(qr_png(invitation)), invitation)

    def test_unavailable_worker_never_falls_back_to_in_process_codec(self):
        from mehrchat.contact_invite import decode_image
        with patch('mehrchat.media.run_isolated_decoder', side_effect=OSError('No sandbox')):
            with self.assertRaises(OSError):
                decode_image(b'not an image')

    def test_oversized_qr_rejected_before_worker(self):
        from mehrchat.contact_invite import decode_image
        with patch('mehrchat.media.run_isolated_decoder') as worker:
            with self.assertRaises(ValueError):
                decode_image(b'x' * (4 * 1024 * 1024 + 1))
            worker.assert_not_called()


class BuildIntegrityTests(unittest.TestCase):
    def test_workflow_actions_have_immutable_full_commit_refs(self):
        import re
        from pathlib import Path
        for path in Path('.github/workflows').glob('*.yml'):
            for action in re.findall(r'uses:\s*(\S+)', path.read_text()):
                self.assertRegex(action, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$', str(path))
