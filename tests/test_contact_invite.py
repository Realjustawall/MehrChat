import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mehrchat.contact_invite import address, normalize, check_address, invite, parse_invite, qr_png
from mehrchat.crypto import create_identity, public_card
from mehrchat.server import Relay
from mehrchat.wire import connect


class ContactInviteTests(unittest.TestCase):
    def setUp(self):
        self.identity = create_identity('alice', 'علی')
        self.card = public_card(self.identity)

    def test_stable_address_survives_profile_change(self):
        before = address(self.card)
        self.identity.update(username='alice_new', name='نام تازه')
        self.assertEqual(before, address(public_card(self.identity)))
        self.assertRegex(before[0], r'^[0-9]{12}$')
        self.assertRegex(before[1], r'^[A-Z]{5}$')

    def test_persian_digits_and_lowercase_code(self):
        self.assertEqual(normalize('۱۲۳۴ ۵۶۷۸ ۹۰۱۲', 'abcde'), ('123456789012', 'ABCDE'))
        for number, code in [('123', 'ABCDE'), ('1'*12, '12ABC'), ('1'*13, 'ABCDE'), ('1'*12, 'ABCDΕ')]:
            with self.assertRaises(ValueError): normalize(number, code)

    def test_qr_roundtrip_contains_only_public_material(self):
        result = invite(self.card)
        card, number, code = parse_invite(result)
        self.assertEqual(card, self.card)
        self.assertEqual((number, code), address(self.card))
        self.assertNotIn(self.identity['box_secret'], result)
        self.assertNotIn(self.identity['sign_secret'], result)

    def test_relay_cannot_substitute_unrelated_signed_identity(self):
        other = public_card(create_identity('bobby', 'بابک'))
        with self.assertRaises(ValueError): check_address(other, *address(self.card))
        bad = invite(other)
        n, key = address(other)
        wanted_n, wanted_key = address(self.card)
        with self.assertRaises(ValueError): parse_invite(bad.replace(n,wanted_n).replace(key,wanted_key))

    def test_tampered_signature_and_non_contact_qrs_rejected(self):
        bad=copy.deepcopy(self.card);bad['body']['name']='جعلی'
        with self.assertRaises(Exception): invite(bad)
        valid=invite(self.card)
        for raw in ['https://example.com', valid+'&v=1', valid+'#fragment', valid.replace('v=1','v=2'), 'x'*9000]:
            with self.assertRaises(ValueError): parse_invite(raw)

    def test_generated_qr_decodes_from_pixels(self):
        from PIL import Image
        import zxingcpp, io
        payload=invite(self.card)
        result=zxingcpp.read_barcode(Image.open(io.BytesIO(qr_png(payload))))
        self.assertIsNotNone(result)
        self.assertEqual(parse_invite(result.text)[0],self.card)

    def test_public_directory_migration_and_offline_lookup_survive_restart(self):
        with tempfile.TemporaryDirectory() as root:
            db=sqlite3.connect(Path(root)/'queue.sqlite')
            db.execute('CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL)');db.close()
            relay=Relay(root);relay.register(self.card)
            self.assertEqual(relay.lookup_address(*address(self.card))['card'],self.card)
            n,key=address(self.card)
            self.assertIsNone(relay.lookup_address(n, 'AAAAA' if key!='AAAAA' else 'BBBBB')['card'])
            relay.db.close()
            relay=Relay(root)
            self.assertFalse(relay.live_cards)
            self.assertEqual(relay.lookup_address(n,key)['card'],self.card)
            # Only the signed public card is stored, never private identity fields.
            stored=relay.db.execute('SELECT public_card FROM users').fetchone()[0]
            self.assertNotIn('secret',stored)
            relay.db.close()

    def test_real_authenticated_network_lookup(self):
        async def run():
            with tempfile.TemporaryDirectory() as root:
                relay=Relay(root);relay.register(self.card)
                server=await asyncio.start_server(relay.handle,'127.0.0.1',0)
                caller=create_identity('bobby','بابک')
                channel=await connect('127.0.0.1',server.sockets[0].getsockname()[1],relay.pin,caller,public_card(caller))
                try:
                    n,key=address(self.card)
                    await channel.send({'op':'lookup_code','number':n,'code':key.lower()})
                    result=await channel.recv()
                    self.assertEqual(check_address(result['card'],n,key)['id'],self.card['body']['id'])
                finally:
                    await channel.close()
                    server.close();await server.wait_closed()
                    await asyncio.sleep(.05)
                    relay.db.close()
        asyncio.run(run())
