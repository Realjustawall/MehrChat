"""CI-only GUI exercise, enabled explicitly through the launcher's smoke-test mode.
Always uses a temporary vault; never reads the interactive user's account.
"""

import io, json, os, time
from pathlib import Path
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Fbo, ClearColor, ClearBuffers, Scale, Translate
from kivy.core.image import Image as CoreImage
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from .crypto import create_identity, public_card
from . import ratchet
from nacl.utils import random

PASSWORD = "CI-only temporary test password"
TEXT = "سلام، آزمون پیام فارسی"


def install(app, result_path):
    app.test_mode = True
    deadline = time.monotonic() + 65
    gallery = os.environ.get("MEHRCHAT_SMOKE_GALLERY")
    gallery = Path(gallery) if gallery else None
    if gallery:
        gallery.mkdir(parents=True, exist_ok=True)
    def capture(name):
        if gallery:
            target = gallery / (name + ".png")
            # Render the actual top-level canvases, including popups, into an FBO.
            # ANGLE can return a black image when reading the default framebuffer.
            layers = sorted((Window.canvas.indexof(w.canvas), w.canvas) for w in Window.children
                            if Window.canvas.indexof(w.canvas) >= 0)
            fbo = Fbo(size=Window.size, with_stencilbuffer=True)
            with fbo:
                ClearColor(*Window.clearcolor)
                ClearBuffers()
                Scale(1, -1, 1)
                Translate(0, -Window.height, 0)
            try:
                for _, canvas in layers:
                    Window.canvas.remove(canvas)
                    fbo.add(canvas)
                fbo.draw()
                pixels = fbo.texture.pixels
                colors = {pixels[i:i+3] for i in range(0, len(pixels), 4 * 37)}
                assert len(colors) > 32, "UI gallery capture is blank: " + name
                CoreImage(fbo.texture).save(str(target))
            finally:
                for index, canvas in layers:
                    fbo.remove(canvas)
                    Window.canvas.insert(index, canvas)
                Window.canvas.ask_update()
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
            next(w for w in widgets if isinstance(w, Button) and w.text == fa("تأیید")).dispatch("on_release")
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
        app.engine.send(chat, 'سلام! چطوری؟ 😊 امروز وقت داری درباره پروژه صحبت کنیم؟')
        app.engine.send(chat, 'پیام طولانی برای بررسی اندازه حباب و شکستن درست متن فارسی، English و شناسه‌های بدون فاصله: ' + 'ABC123'*12 + ' 🎉 ❤️')
        app.compose.text = 'سلام\n😊 ❤️\nEnglish'
        for logical, texture in zip(app.compose._lines, app.compose._lines_labels):
            if not logical.strip():
                continue
            rgba = texture.pixels
            assert any(rgba[i+3] > 0 and min(rgba[i:i+3]) < 180 for i in range(0,len(rgba),4)), 'Multiline composer lost a visible text line'
        private_draft = "پیش‌نویس خصوصی"
        group_draft = "پیش‌نویس گروه"
        app.compose.text = private_draft
        app.group_dialog()
        widgets = list(app.open_popups[-1].content.walk())
        next(w for w in widgets if isinstance(w, TextInput) and w.hint_text == "نام گروه").text = "گروه آزمون"
        members = [w for w in widgets if isinstance(w, CheckBox)]
        assert len(members) == 1
        members[0].active = True
        next(w for w in widgets if isinstance(w, Button) and w.text == fa("ساخت گروه")).dispatch("on_release")
        group = app.chat
        assert group in app.engine.d["groups"]
        assert app.compose.text == "", "A draft must never move to another recipient"
        app.compose.text = group_draft
        app.select(chat)
        assert app.compose.text == private_draft
        app.select(group)
        assert app.compose.text == group_draft
        # Import/confirmation must also go through the same recipient-switch path.
        app.contact_dialog()
        from .contact_invite import invite, address, decode_image, qr_png
        app._contact_fill_invite(invite(peer))
        assert app._contact_form['number'].text == address(peer)[0]
        assert app._contact_form['secret'].text == address(peer)[1]
        # Decode the actual QR pixels using the platform scanner, then fill and add.
        encoded_qr = qr_png(invite(peer))
        decoded = decode_image(encoded_qr)
        if platform == 'android':
            # Exercise the exact ZXing luminance decoder used by the camera.
            from .contact_invite import decode_android_luminance
            image=CoreImage(io.BytesIO(encoded_qr),ext='png').texture
            rgba=image.pixels
            gray=bytes(rgba[i] for i in range(0,len(rgba),4))
            width,height=map(int,image.size)
            assert decode_android_luminance(width,height,gray)==decoded
        app._contact_fill_invite(decoded)
        widgets = list(app.open_popups[-1].content.walk())
        next(w for w in widgets if isinstance(w, Button) and w.text == fa("افزودن")).dispatch("on_release")
        assert app.chat == chat and app.compose.text == private_draft
        app.select(group)
        assert app.compose.text == group_draft
        steps = [
            ("03-private-chat", lambda: app.select(chat)),
            ("04-group-chat", lambda: app.select(group)),
            ("05-chat-list", app.show_chat_list if app.mobile else lambda: None),
            ("06-connection-settings", app.settings),
            ("07-profile", app.profile_dialog),
            ("08-password", app.password_dialog),
            ("09-identity-card", app.my_card),
            ("10-add-contact", app.contact_dialog),
            ("11-edit-group", lambda: app.group_dialog(group)),
            ("12-chat-info", app.chat_info),
            ("13-emoji-picker", app.emoji_picker),
        ]
        pending_capture = None

        def next_step(*_):
            nonlocal pending_capture
            if pending_capture:
                if pending_capture == '03-private-chat':
                    assert app.compose.text == private_draft
                    for logical, rect in zip(app.compose._lines, app.compose._lines_rects):
                        if logical.strip():
                            assert max(rect.tex_coords[1::2])-min(rect.tex_coords[1::2]) > 0, 'Composer cropped a zero-height texture region'
                    from .visual import widget_pixels
                    pixels = widget_pixels(app.compose)
                    assert any(pixels[i+3] and max(pixels[i:i+3])<180 for i in range(0,len(pixels),4)), 'No visible composed draft text'
                    assert any(pixels[i+3] and min(pixels[i:i+3])>210 for i in range(0,len(pixels),4)), 'Composer render lost its background'
                capture(pending_capture)
            for popup in list(app.open_popups):
                popup.dismiss()
            if steps:
                pending_capture, action = steps.pop(0)
                action()
                Clock.schedule_once(next_step, 0.35 if gallery else 0.15)
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
                next(w for w in widgets if isinstance(w, Button) and w.text == fa("بازیابی")).dispatch("on_release")
                app.choose_document = original_picker
                assert app.engine is not None and app.engine.me == identity
                assert app.engine.d["drafts"][chat] == private_draft
                assert any(m.get("text") == TEXT for m in app.engine.d["messages"][chat])
                for popup in list(app.open_popups):
                    popup.dismiss()

                def finish(*_):
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
                    # A hidden fixed-width sidebar must not push the mobile chat off-screen.
                    app.mobile = True
                    body = app.sidebar.parent
                    app.show_chat_list()
                    body.do_layout()
                    assert app.mainpane.width == 0
                    app.select(chat)
                    body.do_layout()
                    assert app.sidebar.width == 0
                    assert app.mainpane.right <= app.root.width + 1
                    result = dict(
                        composed_draft_visible=True,
                        multiline_emoji_composer=True,
                        contact_qr_pixel_decode=True,
                        contact_invite_autofill=True,
                        responsive_navigation=True,
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
                    )
                    if network:
                        result["tcp_noise_e2ee_request_reply"] = True
                        assert network["relay"]["transport"] == "tls"
                        result["tls_noise_e2ee_request_reply"] = True
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

    def gallery_start(*_):
        if not gallery:
            login()
            return
        app.connection_screen()
        def connection_shown(*_):
            capture("01-connect")
            app.unlock_screen()
            def login_shown(*_):
                capture("02-login")
                login()
            Clock.schedule_once(login_shown, .35)
        Clock.schedule_once(connection_shown, .35)
    Clock.schedule_once(gallery_start, 0.3)
