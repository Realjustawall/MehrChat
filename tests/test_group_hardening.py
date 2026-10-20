"""Membership changes must not leak queued content or auto-trust identities."""
import copy
import time
import unittest
from unittest.mock import patch
from test_security import clients, pump
from mehrchat.crypto import signed


class GroupHardeningTests(unittest.TestCase):
    def setUp(self):
        self.engines = clients()
        self.a, self.b, self.c = self.engines
        self.gid = self.a.create_group('Group', [self.b.me, self.c.me])
        pump(self.engines)

    def test_unverified_group_card_cannot_receive_new_outbound_content(self):
        self.b.d['contacts'].pop(self.c.me)
        before = copy.deepcopy(self.b.d)
        with self.assertRaises(ValueError):
            self.b.send(self.gid, 'must not leak')
        self.assertEqual(before, self.b.d)

    def test_removal_cancels_encrypted_outbox_and_preserves_private_messages(self):
        self.b.send(self.gid, 'queued group')
        self.b.send(self.b.dm_id(self.c.me), 'private unaffected')
        self.a.update_group(self.gid, 'Group', [self.b.me])
        update = next(p['item'] for p in self.a.d['outbox'] if p['item']['body']['to'] == self.b.me)
        self.b.ingest(update)
        self.assertFalse(any(p['chat'] == self.gid and p['item']['body']['to'] == self.c.me for p in self.b.d['outbox']))
        self.assertTrue(any(p['chat'] == self.b.dm_id(self.c.me) for p in self.b.d['outbox']))
        self.assertTrue(any(key.startswith('membership:') for key in self.b.d['pending_retractions']))

    def test_removal_cancels_pending_plaintext_before_bootstrap_flush(self):
        self.b.d['sessions'].pop(self.c.me)
        self.b.send(self.gid, 'pending group')
        self.assertTrue(self.b.d['pending_secure'][self.c.me])
        self.a.update_group(self.gid, 'Group', [self.b.me])
        update = next(p['item'] for p in self.a.d['outbox'] if p['item']['body']['to'] == self.b.me)
        self.b.ingest(update)
        self.assertFalse(any(p['chat'] == self.gid for p in self.b.d['pending_secure'][self.c.me]))

    def test_removed_local_member_stops_all_queued_group_content(self):
        self.c.send(self.gid, 'must stop')
        self.a.update_group(self.gid, 'Group', [self.b.me])
        update = next(p['item'] for p in self.a.d['outbox'] if p['item']['body']['to'] == self.c.me)
        self.c.ingest(update)
        self.assertFalse(any(p['chat'] == self.gid and p['item']['body']['kind'] != 'group_update' for p in self.c.d['outbox']))
        with self.assertRaises(ValueError):
            self.c.send(self.gid, 'removed')

    def test_rejected_membership_transition_rolls_back_queue_changes(self):
        self.a.send(self.gid, 'still queued')
        before = copy.deepcopy(self.a.d)
        with patch.object(self.a.vault, 'save', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                self.a.update_group(self.gid, 'Changed', [self.b.me])
        self.assertEqual(before, self.a.d)

    def test_chainless_descriptor_cannot_downgrade_validation(self):
        group = self.a.d['groups'][self.gid]
        with self.assertRaises(ValueError):
            self.b.validate_chat(signed(self.a.identity, group['body']), self.a.me)

    def test_boolean_epoch_is_rejected_even_with_valid_owner_signature(self):
        group = copy.deepcopy(self.a.d['groups'][self.gid])
        group['body']['epoch'] = False
        group['chain'][0] = signed(self.a.identity, group['body'])
        with self.assertRaises(ValueError):
            self.b.validate_chat(group, self.a.me)

    def test_member_cannot_introduce_new_group_without_creator_delivery(self):
        self.c.d['groups'].pop(self.gid)
        self.b.send(self.gid, 'unsolicited introduction')
        packet = next(p['item'] for p in self.b.d['outbox'] if p['item']['body']['to'] == self.c.me)
        before = copy.deepcopy(self.c.d)
        with self.assertRaises(ValueError):
            self.c.ingest(packet)
        self.assertEqual(before, self.c.d)

    def test_safety_code_agrees_and_changes_after_membership_change(self):
        code = self.a.groups.safety_code(self.a.d['groups'][self.gid])
        self.assertEqual(code, self.b.groups.safety_code(self.b.d['groups'][self.gid]))
        self.a.update_group(self.gid, 'Group', [self.b.me])
        pump(self.engines)
        new = self.b.groups.safety_code(self.b.d['groups'][self.gid])
        self.assertNotEqual(code, new)
        self.assertEqual(new, self.a.groups.safety_code(self.a.d['groups'][self.gid]))

    def test_group_name_cannot_use_bidi_override_or_control_characters(self):
        for name in ('admin\u202eevil', 'bad\nname', '   '):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.a.create_group(name, [self.b.me])
