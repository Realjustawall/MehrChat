"""CI-only GUI exercise, enabled explicitly through the launcher's smoke-test mode.
Always uses a temporary vault; never reads the interactive user's account.
"""

import io, json, os, time
from pathlib import Path
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from .crypto import create_identity, public_card
from . import ratchet
from .i18n import tr, language
from nacl.utils import random

PASSWORD = "CI-only temporary test password"
TEXT = "سلام، آزمون پیام فارسی"


def check_layout_matrix(app, done):
    """Inspect live geometry after layout ticks, not only nonempty screenshots."""
    from kivy.core.window import Window
    from kivy.metrics import dp
    from .ui import platform
    original_size = Window.size
    original_language = language()
    chat = next(cid for cid, _ in app.chats())
    sizes = [original_size] if platform == 'android' else [(dp(320), dp(568)), (dp(390), dp(760)), (dp(540), dp(760)), (dp(1100), dp(760))]
    tasks = [(size, locale, mode) for size in sizes for locale in ('fa', 'en') for mode in ('list', 'chat')]

    def step(*_):
        if not tasks:
            Window.size = original_size
            if language() != original_language:
                app.change_language()
            app.show_chat_list()
            Clock.schedule_once(lambda *_: done(), 0.15)
            return
        size, locale, mode = tasks.pop(0)
        Window.size = size
        if language() != locale:
            app.change_language()
        app.select(chat) if mode == 'chat' else app.show_chat_list()

        def inspect(*_):
            panes = [app.sidebar, app.mainpane] if not app.mobile else [app.sidebar if mode == 'list' else app.mainpane]
            for pane in panes:
                assert pane.parent is app.body, ('unmounted pane', locale, mode)
                assert -1 <= pane.x and pane.right <= Window.width + 1, ('pane overflow', locale, mode, pane.pos, pane.size, Window.size)
                for widget in pane.walk():
                    if isinstance(widget, (Button, TextInput)):
                        assert widget.x >= -1 and widget.right <= Window.width + 1, ('control overflow', locale, mode, getattr(widget, 'text', ''), widget.pos, widget.size)
                        assert widget.width > 1, ('collapsed control', locale, mode)
            if app.mobile:
                assert len(app.body.children) == 1
            Clock.schedule_once(step, 0)
        Clock.schedule_once(inspect, 0.15)
    step()


def install(app, result_path):
    deadline = time.monotonic() + 35
    config_path = os.environ.get("MEHRCHAT_SMOKE_NETWORK_CONFIG")
    network = json.loads(Path(config_path).read_text()) if config_path else None

    def login(*_):
        # Android's Java UI-thread acknowledgement is asynchronous. A slow
        # first frame must not turn an early simulated click into a false timeout.
        if not app.screen_protection_done:
            assert time.monotonic() < deadline, "Screen protection acknowledgement timed out"
            Clock.schedule_once(login, 0.1)
            return
        assert app.screen_protected, "Screen protection setup failed; inspect the safe setup diagnostic"
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
        assert app.open_popups, "New accounts must be shown the external backup reminder"
        from .ui import fa, platform
        if platform == "android":
            assert app.open_popups[-1].auto_dismiss is False
        setup_backup = io.BytesIO()
        picker = app.choose_document
        reminder = app.open_popups[-1]
        app.choose_document = lambda mode, name, callback: callback(setup_backup)
        app.backup_dialog(on_saved=reminder.dismiss)
        app.choose_document = picker
        assert setup_backup.getvalue().startswith(b"MEHRVAULT1\0")
        assert app.engine.d["backup_last_at"] > 0 and reminder not in app.open_popups
        if platform != "android":
            failed_output = app.vault_path.parent / "failed-export.mcv"

            def fail_export(stream):
                stream.write(b"partial encrypted output")
                raise OSError("simulated disk full")

            app.choose_document("save", "failed-export.mcv", fail_export)
            widgets = list(app.open_popups[-1].content.walk())
            next(w for w in widgets if isinstance(w, TextInput)).text = str(failed_output)
            next(w for w in widgets if isinstance(w, Button) and w.text == fa(tr("تأیید"))).dispatch("on_release")
            assert not failed_output.exists(), "The GUI must remove its partial export"
            for popup in list(app.open_popups):
                popup.dismiss()
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
        private_draft = "پیش‌نویس خصوصی"
        group_draft = "پیش‌نویس گروه"
        app.compose.text = private_draft
        app.group_dialog()
        widgets = list(app.open_popups[-1].content.walk())
        next(w for w in widgets if isinstance(w, TextInput) and w.hint_text == tr("نام گروه")).text = "گروه آزمون"
        members = [w for w in widgets if isinstance(w, CheckBox)]
        assert len(members) == 1
        members[0].active = True
        next(w for w in widgets if isinstance(w, Button) and w.text == fa(tr("ساخت گروه"))).dispatch("on_release")
        group = app.chat
        assert group in app.engine.d["groups"]
        assert app.compose.text == "", "A draft must never move to another recipient"
        app.compose.text = group_draft
        app.select(chat)
        assert app.compose.text == private_draft
        app.select(group)
        assert app.compose.text == group_draft
        original_language = language()
        app.change_language()
        assert language() != original_language and app.compose.text == group_draft
        assert any(isinstance(w, Button) and w.text == fa(tr("ارسال")) for w in app.rootbox.walk())
        app.change_language()
        assert language() == original_language and app.compose.text == group_draft
        # Import/confirmation must also go through the same recipient-switch path.
        app.contact_dialog()
        widgets = list(app.open_popups[-1].content.walk())
        next(w for w in widgets if isinstance(w, TextInput) and w.hint_text == tr("کارت هویت مخاطب")).text = json.dumps(peer)
        next(w for w in widgets if isinstance(w, TextInput) and w.hint_text == tr("اثر انگشت تأییدشده")).text = peer["body"]["id"]
        next(w for w in widgets if isinstance(w, Button) and w.text == fa(tr("افزودن"))).dispatch("on_release")
        assert app.chat == chat and app.compose.text == private_draft
        app.select(group)
        assert app.compose.text == group_draft
        steps = [
            app.settings,
            app.privacy_dialog,
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
            old_messages, old_compose = app.messagebox, app.compose
            app.lock_account()
            assert app.engine is None
            assert old_compose.text == "" and not old_compose._undo
            assert all(not w.text for w in old_messages.walk() if isinstance(w, Label))
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
                assert app.engine.d["drafts"][chat] == private_draft
                assert app.engine.d["drafts"][group] == group_draft
                # Exercise the actual UI backup callback and restore dialog. Only
                # this smoke launcher's temporary account is removed, never user data.
                backup = io.BytesIO()
                original_picker = app.choose_document
                app.choose_document = lambda mode, name, callback: callback(backup)
                app.backup_dialog()
                raw_backup = backup.getvalue()
                assert app.engine.d["backup_last_at"] > 0
                assert TEXT.encode() not in raw_backup
                app.lock_account()
                app.vault_path.unlink()
                app.choose_document = lambda mode, name, callback: callback(io.BytesIO(raw_backup))
                app.restore_dialog()
                from kivy.uix.textinput import TextInput
                from kivy.uix.button import Button
                from .ui import fa

                restore_popup = app.open_popups[-1]
                widgets = list(restore_popup.content.walk())
                next(w for w in widgets if isinstance(w, TextInput) and w.password).text = PASSWORD
                next(w for w in widgets if isinstance(w, Button) and w.text == fa(tr("بازیابی"))).dispatch("on_release")
                app.choose_document = original_picker
                assert app.engine is not None and app.engine.me == identity
                assert app.engine.d["drafts"][chat] == private_draft
                assert any(m.get("text") == TEXT for m in app.engine.d["messages"][chat])
                for popup in list(app.open_popups):
                    popup.dismiss()

                def finish(*_):
                    if not getattr(app, '_layout_matrix_complete', False):
                        def checked():
                            app._layout_matrix_complete = True
                            finish()
                        check_layout_matrix(app, checked)
                        return
                    assert len(app.chatlist.children) == len(app.chats())
                    for row in app.chatlist.children:
                        for widget in row.walk():
                            if isinstance(widget, Label) and widget.text.strip():
                                assert widget.texture is not None and widget.texture.width > 1
                    before = tuple(app.chatlist.children)
                    app.refresh()
                    assert before == tuple(app.chatlist.children), "Unchanged status must not rebuild the chat list"
                    screenshot = os.environ.get("MEHRCHAT_SMOKE_SCREENSHOT")
                    if screenshot:
                        app.root.export_to_png(screenshot)
                        pixels = CoreImage(screenshot).texture.pixels
                        colors = {pixels[i:i + 3] for i in range(0, len(pixels), 4 * 37)}
                        assert len(colors) > 32, "The captured UI must not be blank"
                    result = dict(
                        account_creation=True,
                        compiled_double_ratchet=True,
                        persian_chat=True,
                        group=True,
                        dialogs=True,
                        vault_encrypted=True,
                        lock_unlock=True,
                        identity_preserved=True,
                        backup_reminder=True,
                        encrypted_backup_restore_dialog=True,
                        drafts_isolated_and_restored=True,
                        stable_chat_list_and_rendered_text=True,
                        bilingual_switch_preserves_drafts=True,
                        screen_protection_ready=app.screen_protected,
                        lock_scrubs_text_and_undo=True,
                        viewport_controls_inside_screen=True,
                    )
                    if network:
                        result["tcp_noise_e2ee_request_reply"] = True
                    Path(result_path).write_text(json.dumps(result))
                    print("NATIVE_GUI_FLOW_PASS", flush=True)
                    app.stop()

                Clock.schedule_once(finish, 1.5)
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
