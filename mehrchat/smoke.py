"""CI-only GUI exercise, enabled explicitly through the launcher's smoke-test mode.
Always uses a temporary vault; never reads the interactive user's account.
"""

import json, os, time
from pathlib import Path
from kivy.clock import Clock
from .crypto import create_identity, public_card
from . import ratchet
from nacl.utils import random

PASSWORD = "CI-only temporary test password"
TEXT = "سلام، آزمون پیام فارسی"


def install(app, result_path):
    deadline = time.monotonic() + 35
    config_path = os.environ.get("MEHRCHAT_SMOKE_NETWORK_CONFIG")
    network = json.loads(Path(config_path).read_text()) if config_path else None

    def login(*_):
        app.username.text = "ci_tester"
        app.displayname.text = "آزمون"
        app.password.text = PASSWORD
        app.unlock()
        Clock.schedule_interval(ready, 0.1)

    def ready(*_):
        if time.monotonic() > deadline:
            raise AssertionError("GUI login timed out")
        if app.engine is None:
            return True
        peer = (
            network["card"]
            if network
            else public_card(create_identity("ci_peer", "مخاطب"))
        )
        # Exercise compiled crypto extensions and serialized Double Ratchet state.
        recipient = ratchet.private_key()
        secret, ad = random(32), b"MehrChat compiled GUI CI"
        alice, packet = ratchet.initial_send(
            secret, ratchet.public_key(recipient), b"hello", ad
        )
        bob, plaintext = ratchet.initial_receive(secret, recipient, packet, ad)
        assert plaintext == b"hello"
        bob, reply = ratchet.encrypt(bob, b"reply", ad)
        alice, plaintext = ratchet.decrypt(alice, reply, ad)
        assert plaintext == b"reply"
        app.engine.add_contact(json.dumps(peer), peer["body"]["id"])
        if network:
            app.engine.configure_relays([network["relay"]])
        chat = app.engine.dm_id(peer["body"]["id"])
        app.select(chat)
        app.compose.text = TEXT
        app.send()
        assert any(m.get("text") == TEXT for m in app.engine.d["messages"][chat])
        group = app.engine.create_group("گروه آزمون", [peer["body"]["id"]])
        app.select(group)
        steps = [
            app.settings,
            app.profile_dialog,
            app.password_dialog,
            app.my_card,
            app.contact_dialog,
            lambda: app.group_dialog(group),
            app.chat_info,
        ]

        def next_step(*_):
            for popup in list(app.open_popups):
                popup.dismiss()
            if steps:
                steps.pop(0)()
                Clock.schedule_once(next_step, 0.15)
                return
            raw = app.vault_path.read_bytes()
            assert TEXT.encode() not in raw and PASSWORD.encode() not in raw
            identity = app.engine.me
            app.lock_account()
            assert app.engine is None
            app.password.text = PASSWORD
            app.unlock()

            def restored(*_):
                if time.monotonic() > deadline:
                    raise AssertionError("GUI restore timed out")
                if app.engine is None:
                    return True
                assert app.engine.me == identity and any(
                    m.get("text") == TEXT for m in app.engine.d["messages"][chat]
                )

                def finish(*_):
                    screenshot = os.environ.get("MEHRCHAT_SMOKE_SCREENSHOT")
                    if screenshot:
                        app.root.export_to_png(screenshot)
                    result = dict(
                        account_creation=True,
                        compiled_double_ratchet=True,
                        persian_chat=True,
                        group=True,
                        dialogs=True,
                        vault_encrypted=True,
                        lock_unlock=True,
                        identity_preserved=True,
                    )
                    if network:
                        result["tcp_noise_e2ee_request_reply"] = True
                    Path(result_path).write_text(json.dumps(result))
                    print("NATIVE_GUI_FLOW_PASS", flush=True)
                    app.stop()

                Clock.schedule_once(finish, 0.3)
                return False

            Clock.schedule_interval(restored, 0.1)

        if network:

            def network_ready(*_):
                if time.monotonic() > deadline:
                    raise AssertionError("Android encrypted network reply timed out")
                if not any(
                    m["author"] == peer["body"]["id"]
                    and m.get("text") == network["expected_reply"]
                    for m in app.engine.d["messages"].get(chat, [])
                ):
                    return True
                Clock.schedule_once(next_step, 0.2)
                return False

            Clock.schedule_interval(network_ready, 0.1)
        else:
            Clock.schedule_once(next_step, 0.2)
        return False

    Clock.schedule_once(login, 0.3)
