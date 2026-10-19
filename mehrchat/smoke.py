"""CI-only GUI exercise, enabled explicitly through the launcher's smoke-test mode.
Always uses a temporary vault; never reads the interactive user's account.
"""

import json, time
from pathlib import Path
from kivy.clock import Clock
from .crypto import create_identity, public_card

PASSWORD = "CI-only temporary test password"
TEXT = "سلام، آزمون پیام فارسی"


def install(app, result_path):
    deadline = time.monotonic() + 35

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
        peer = public_card(create_identity("ci_peer", "مخاطب"))
        app.engine.add_contact(json.dumps(peer), peer["body"]["id"])
        chat = app.engine.dm_id(peer["body"]["id"])
        app.select(chat)
        app.compose.text = TEXT
        app.send()
        assert app.engine.d["messages"][chat][-1]["text"] == TEXT
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
                assert (
                    app.engine.me == identity
                    and app.engine.d["messages"][chat][-1]["text"] == TEXT
                )
                Path(result_path).write_text(
                    json.dumps(
                        {
                            "account_creation": True,
                            "persian_chat": True,
                            "group": True,
                            "dialogs": True,
                            "vault_encrypted": True,
                            "lock_unlock": True,
                            "identity_preserved": True,
                        }
                    )
                )
                print("NATIVE_GUI_FLOW_PASS", flush=True)
                app.stop()
                return False

            Clock.schedule_interval(restored, 0.1)

        Clock.schedule_once(next_step, 0.2)
        return False

    Clock.schedule_once(login, 0.3)
