import json
import asyncio
import os
from pathlib import Path
import tempfile
import threading
import time
import re
import textwrap
import arabic_reshaper
from bidi.algorithm import get_display
from kivy.config import Config
from kivy.utils import platform

if platform != "android":
    Config.set("graphics", "width", "1100")
    Config.set("graphics", "height", "760")
from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform
from .vault import Vault, MAX_BACKUP_BYTES
from .client import Engine, safe_filename
from .crypto import public_card, check_card
from .connection import bundled_profile, validate_profile, probe
from . import __version__

ROOT = Path(__file__).resolve().parent.parent
FONT = str(ROOT / "assets" / "Vazirmatn-Regular.ttf")
BG = (0.055, 0.085, 0.12, 1)
PANEL = (0.09, 0.13, 0.175, 1)
BLUE = (0.28, 0.64, 0.87, 1)
TEXT = (0.88, 0.93, 0.96, 1)


def fa(s):
    return get_display(arabic_reshaper.reshape(str(s)))


class Surface(BoxLayout):
    def __init__(self, color=PANEL, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.bind(pos=self.update_rect, size=self.update_rect)

    def update_rect(self, *_):
        self.rect.pos, self.rect.size = self.pos, self.size


class ChatRow(ButtonBehavior, Surface):
    def on_press(self):
        Animation(opacity=0.72, duration=0.08).start(self)

    def on_release(self):
        Animation(opacity=1, duration=0.12).start(self)


class ModernButton(Button):
    def __init__(self, **kw):
        color = kw.pop("background_color", BLUE)
        super().__init__(background_color=(0, 0, 0, 0), background_normal="", background_down="", **kw)
        with self.canvas.before:
            self.fill = Color(*color)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(1, 1, 1, 1)
        self.bind(pos=self.redraw, size=self.redraw, state=self.redraw, disabled=self.redraw)
        self.base_color = color

    def redraw(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size
        factor = 0.75 if self.state == "down" or self.disabled else 1
        self.fill.rgba = tuple(c * factor for c in self.base_color[:3]) + (self.base_color[3],)



class Avatar(Surface):
    def __init__(self, name, identity, **kw):
        palette = [
            (0.25, 0.56, 0.69, 1),
            (0.43, 0.42, 0.69, 1),
            (0.31, 0.59, 0.48, 1),
            (0.70, 0.45, 0.34, 1),
        ]
        super().__init__(
            color=palette[int(identity[:2], 16) % len(palette)],
            size_hint=(None, None),
            size=(dp(48), dp(48)),
            **kw
        )
        self.rect.radius = [dp(24)]
        self.add_widget(label(name.strip()[:1], font_size=dp(23)))


def label(text="", **kw):
    kw.setdefault("font_size", dp(16))
    return Label(text=fa(text), font_name=FONT, color=TEXT, **kw)


def wrapped_label(text, **kw):
    widget = label("", halign="right", valign="middle", **kw)

    def fit(*_):
        # Wrap logical Persian before bidi shaping; wrapping the visual string
        # reverses sentence fragments on narrow screens.
        columns = max(8, int(widget.width / (widget.font_size * 0.65)))
        lines = ["\n".join(textwrap.wrap(line, columns) or [""]) for line in str(text).split("\n")]
        widget.text_size = widget.size
        widget.text = fa("\n".join(lines))

    widget.bind(size=fit, font_size=fit)
    fit()
    return widget


def button(text, callback, **kw):
    color = kw.pop("background_color", BLUE)
    b = ModernButton(
        text=fa(text),
        font_name=FONT,
        font_size=dp(15),
        background_color=color,
        size_hint_y=None,
        height=dp(44),
        **kw
    )
    b.bind(on_release=lambda *_: callback())
    return b


class PersianInput(TextInput):
    def __init__(self, **kw):
        kw.update(background_normal="", background_active="", background_color=(0, 0, 0, 0))
        super().__init__(**kw)
        with self.canvas.before:
            self.fill = Color(0.13, 0.18, 0.235, 1)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(1, 1, 1, 1)
        self.bind(pos=self.redraw, size=self.redraw, focus=self.redraw)

    def redraw(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size
        self.fill.rgba = (0.16, 0.23, 0.30, 1) if self.focus else (0.13, 0.18, 0.235, 1)

    def _get_line_options(self):
        options = getattr(self, "_line_options", None)
        if options and (
            options.get("font_name") != self.font_name
            or options.get("font_size") != self.font_size
        ):
            self._line_options = None
        return super()._get_line_options()

    def _rtl(self, text):
        return bool(re.search(r"[\u0600-\u06ff]", text)) and not self.password

    def _create_line_label(self, text, hint=False):
        return super()._create_line_label(fa(text) if self._rtl(text) else text, hint)

    def _get_text_width(self, text, tab_width, cached):
        self._get_line_options()
        return super()._get_text_width(
            fa(text) if self._rtl(text) else text, tab_width, self._label_cached
        )

    def cursor_offset(self):
        row, col = int(self.cursor_row), int(self.cursor_col)
        if row < len(self._lines) and self._rtl(self._lines[row]):
            line = self._lines[row]
            return self._get_text_width(
                line, self.tab_width, self._label_cached
            ) - self._get_text_width(line[:col], self.tab_width, self._label_cached)
        return super().cursor_offset()

    def get_cursor_from_xy(self, x, y):
        col, row = super().get_cursor_from_xy(x, y)
        if row < len(self._lines) and self._rtl(self._lines[row]):
            line = self._lines[row]
            width = self._get_text_width(line, self.tab_width, self._label_cached)
            start = self.x + self.padding[0]
            if self.halign == "right":
                start = max(start, self.right - self.padding[2] - width)
            offset = max(0, min(width, x - start + self.scroll_x))
            col = min(
                range(len(line) + 1),
                key=lambda i: abs(
                    width
                    - self._get_text_width(line[:i], self.tab_width, self._label_cached)
                    - offset
                ),
            )
        return col, row


def field(hint="", password=False, multiline=False):
    return PersianInput(
        hint_text=hint,
        password=password,
        multiline=multiline,
        font_name=FONT,
        font_size=dp(16),
        background_color=(0.12, 0.18, 0.23, 1),
        foreground_color=TEXT,
        cursor_color=BLUE,
        padding=[dp(12), dp(8)],
        hint_text_color=(0.54, 0.65, 0.74, 1),
        size_hint_y=None,
        height=dp(48) if not multiline else dp(120),
    )


class MehrApp(App):
    title = "مهر"

    def build(self):
        Window.clearcolor = BG
        self.engine = None
        self.chat = None
        self.rootbox = BoxLayout(orientation="vertical", padding=0, spacing=0)
        self.open_popups = []
        self.last_activity = time.monotonic()
        Window.bind(
            on_touch_down=lambda *_: self.activity(),
            on_key_down=lambda *_: self.activity(),
        )
        Window.bind(on_resize=self.resize_layout)
        self.vault_path = self.data_path()
        self.deployment = None if getattr(self, "test_mode", False) else bundled_profile()
        self.connection_profile = self.deployment
        if getattr(self, "test_mode", False):
            self.unlock_screen()
        else:
            self.connection_screen()
        Clock.schedule_interval(lambda *_: self.tick(), 5)
        return self.rootbox

    def resize_layout(self, *_):
        if (
            self.engine
            and hasattr(self, "mobile")
            and self.mobile != (Window.width < dp(720))
        ):
            draft, chat = self.compose.text, self.chat
            self.shell()
            self.compose.text = draft
            if chat:
                self.select(chat)

    def data_path(self):
        if platform == "android":
            return Path(self.user_data_dir) / "identity.mcv"
        base = Path(os.environ.get("APPDATA", str(Path.home() / ".local" / "share")))
        return base / "MehrChat" / "identity.mcv"

    def dialog(self, title, body):
        popup = Popup(
            title=fa(title), title_font=FONT, content=body, size_hint=(0.94, 0.9)
        )
        self.open_popups.append(popup)
        popup.bind(
            on_dismiss=lambda *_: (
                self.open_popups.remove(popup) if popup in self.open_popups else None
            )
        )
        popup.open()
        return popup

    def error(self, message):
        box = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        box.add_widget(wrapped_label(str(message)))
        pop = self.dialog("پیام", box)
        box.add_widget(button("بستن", pop.dismiss))

    def guarded(self, fn):
        try:
            fn()
        except Exception as e:
            self.error(
                str(e)
                if isinstance(e, ValueError) and re.search(r"[\u0600-\u06ff]", str(e))
                else "عملیات انجام نشد؛ اطلاعات را بررسی کنید"
            )

    def setup_panel(self, title, subtitle):
        self.rootbox.clear_widgets()
        scroll = ScrollView(do_scroll_x=False)
        anchor = AnchorLayout(anchor_x="center", anchor_y="center", size_hint_y=None)
        panel = Surface(orientation="vertical", size_hint=(None, None),
                        padding=dp(24), spacing=dp(12))
        panel.bind(minimum_height=panel.setter("height"))
        def fit(*_):
            panel.width = max(dp(240), min(dp(460), scroll.width - dp(32)))
            anchor.height = max(scroll.height, panel.height + dp(40))
        scroll.bind(size=fit)
        panel.bind(height=fit)
        anchor.add_widget(panel)
        scroll.add_widget(anchor)
        self.rootbox.add_widget(scroll)
        panel.add_widget(label("مهر", font_size=dp(38), size_hint_y=None, height=dp(64)))
        panel.add_widget(label(title, font_size=dp(22), size_hint_y=None, height=dp(38)))
        note = wrapped_label(subtitle, font_size=dp(13), size_hint_y=None, height=dp(60))
        note.color = (0.60, 0.70, 0.78, 1)
        panel.add_widget(note)
        Clock.schedule_once(fit)
        return panel

    def connection_screen(self):
        self.connection_verified = False
        panel = self.setup_panel("اتصال امن", "ابتدا سرور را تأیید کنید، سپس وارد حساب شوید")
        current = self.connection_profile
        if not current and self.vault_path.with_suffix(".connection.json").exists():
            try:
                current = validate_profile(json.loads(self.vault_path.with_suffix(".connection.json").read_text()))
            except (OSError, ValueError, KeyError):
                current = None
        current = current or dict(host="127.0.0.1", port=8787, pin="", transport="tls", ca="")
        inputs = {}
        if self.deployment:
            panel.add_widget(label("نسخه " + __version__, size_hint_y=None, height=dp(30)))
            panel.add_widget(label("TLS + Noise NK · SSL فعال", size_hint_y=None, height=dp(36)))
        else:
            for name, hint in (("host", "آدرس سرور"), ("port", "پورت"), ("pin", "کلید عمومی سرور")):
                widget = field(hint)
                widget.text = str(current[name])
                panel.add_widget(widget)
                inputs[name] = widget
            transport = Spinner(text="TLS + Noise" if current['transport'] == 'tls' else 'Noise',
                                values=("TLS + Noise", "Noise"), font_name=FONT,
                                size_hint_y=None, height=dp(48), background_normal="", background_color=PANEL)
            panel.add_widget(transport)
            ca = field("گواهی CA اختصاصی (PEM)، برای گواهی عمومی خالی", multiline=True)
            ca.text = current.get("ca", "")
            # Paste a public profile exported by the Ubuntu installer.
            imported = field("پروفایل اتصال JSON", multiline=True)
            advanced = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(296), spacing=dp(12))
            advanced.add_widget(ca)
            advanced.add_widget(imported)
            def import_profile():
                def apply():
                    self.connection_profile = validate_profile(json.loads(imported.text))
                    self.connection_screen()
                self.guarded(apply)
            advanced.add_widget(button("واردکردن پروفایل", import_profile))
            def toggle_advanced():
                if advanced.parent:
                    panel.remove_widget(advanced)
                else:
                    panel.add_widget(advanced, index=2)
            panel.add_widget(button("پروفایل و گواهی اختصاصی", toggle_advanced, background_color=PANEL))
        status = wrapped_label("آماده بررسی اتصال", size_hint_y=None, height=dp(48), font_size=dp(13))
        panel.add_widget(status)
        def check():
            try:
                profile = self.deployment or validate_profile(dict(
                    host=inputs['host'].text, port=inputs['port'].text, pin=inputs['pin'].text.strip(),
                    transport='tls' if transport.text == 'TLS + Noise' else 'noise', ca=ca.text.strip()))
            except Exception:
                status.text = fa("آدرس، پورت، کلید و گواهی را بررسی کنید")
                return
            connect_button.disabled = True
            status.text = fa("در حال بررسی اتصال امن…")
            def work():
                try:
                    asyncio.run(probe(profile))
                except Exception:
                    def failed(*_):
                        connect_button.disabled = False
                        status.text = fa("اتصال تأیید نشد؛ شبکه، کلید و گواهی را بررسی کنید")
                    Clock.schedule_once(failed)
                    return
                def done(*_):
                    self.connection_profile = profile
                    self.connection_verified = True
                    if not self.deployment:
                        path = self.vault_path.with_suffix('.connection.json')
                        path.parent.mkdir(parents=True, exist_ok=True)
                        temp = path.with_suffix('.tmp')
                        temp.write_text(json.dumps(profile))
                        temp.replace(path)
                    self.unlock_screen()
                Clock.schedule_once(done)
            threading.Thread(target=work, daemon=True).start()
        connect_button = button("بررسی اتصال و ادامه", check)
        panel.add_widget(connect_button)
        if self.deployment:
            Clock.schedule_once(lambda *_: check(), .1)

    def unlock_screen(self):
        self.rootbox.clear_widgets()
        wrap = self.setup_panel("خوش آمدید", "کلیدها و پیام‌های شما در این دستگاه رمزگذاری و نگهداری می‌شوند")
        self.username = field("نام کاربری")
        self.displayname = field("نام نمایشی")
        if not self.vault_path.exists():
            wrap.add_widget(self.username)
            wrap.add_widget(self.displayname)
        self.password = field("رمز عبور", password=True)
        wrap.add_widget(self.password)
        self.loginbutton = button(
            "ورود" if self.vault_path.exists() else "ساخت حساب", self.unlock
        )
        wrap.add_widget(self.loginbutton)
        wrap.add_widget(button("بازیابی پشتیبان", self.restore_dialog))
        if not getattr(self, "test_mode", False):
            wrap.add_widget(button("تنظیم اتصال", self.connection_screen, background_color=PANEL))

    def unlock(self):
        if not getattr(self, "test_mode", False) and not getattr(self, "connection_verified", False):
            self.connection_screen()
            return
        pw = self.password.text
        user = self.username.text.strip()
        name = self.displayname.text.strip()
        self.loginbutton.disabled = True

        def work():
            try:
                vault = Vault(self.vault_path, pw, user, name, exclusive=True)
                Clock.schedule_once(lambda *_: self.enter(vault))
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "رمز عبور یا فایل معتبر نیست"
                )
                Clock.schedule_once(lambda _, m=message: self.unlock_failed(m))

        threading.Thread(target=work, daemon=True).start()

    def unlock_failed(self, message):
        self.loginbutton.disabled = False
        self.error(message)

    def enter(self, vault):
        self.password.text = ""
        vault.acquire_lock()
        self.last_activity = time.monotonic()
        self.engine = Engine(vault)
        if self.connection_profile:
            self.engine.configure_relays([self.connection_profile])
        self.engine.changed = lambda: Clock.schedule_once(lambda *_: self.refresh())
        self.engine.start()
        self.shell()
        if not vault.data.get("backup_last_at"):
            self.backup_reminder()

    def backup_reminder(self):
        box = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
        text = (
            "برای بازیابی حساب، پشتیبان رمزگذاری‌شده را خارج از برنامه ذخیره کنید.\n"
            "با حذف برنامه در اندروید، کلید داخل برنامه پاک می‌شود.\n"
            "رمز پشتیبان را نگه دارید؛ بازیابی بدون آن ممکن نیست."
        )
        notice = wrapped_label(text)
        box.add_widget(notice)
        pop = self.dialog("پشتیبان حساب", box)
        box.add_widget(button("ذخیره پشتیبان", lambda: self.backup_dialog(on_saved=pop.dismiss)))
        if platform == "android":
            # Android deletes private app data on uninstall. Setup must not
            # silently continue after cancelling the external backup picker.
            pop.auto_dismiss = False
            box.add_widget(button("قفل حساب", self.lock_account))
        else:
            box.add_widget(button("بعداً", pop.dismiss))

    def shell(self):
        self.rootbox.clear_widgets()
        self.mobile = Window.width < dp(720)
        self.view_limit = 100
        self._view_signature = None
        self._sidebar_signature = None
        body = BoxLayout(spacing=dp(1))
        self.sidebar = Surface(
            orientation="vertical",
            size_hint_x=None,
            width=dp(348),
            padding=dp(10),
            spacing=dp(4),
        )
        toolbar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        toolbar.add_widget(
            button(
                "منو",
                self.main_menu,
                size_hint_x=None,
                width=dp(62),
                background_color=PANEL,
            )
        )
        toolbar.add_widget(label("مهر", font_size=dp(23)))
        toolbar.add_widget(button("+", self.new_menu, size_hint_x=None, width=dp(44)))
        self.sidebar.add_widget(toolbar)
        self.search = field("جستجو")
        self.search.bind(text=lambda *_: self.refresh())
        self.sidebar.add_widget(self.search)
        caption = label("گفتگوهای شما", font_size=dp(12), size_hint_y=None, height=dp(30))
        caption.color = (0.48, 0.64, 0.76, 1)
        self.sidebar.add_widget(caption)
        scroll = ScrollView()
        self.chatlist = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(2)
        )
        self.chatlist.bind(minimum_height=self.chatlist.setter("height"))
        scroll.add_widget(self.chatlist)
        self.sidebar.add_widget(scroll)
        body.add_widget(self.sidebar)
        self.mainpane = Surface(orientation="vertical", padding=0, spacing=0, color=BG)
        header = Surface(
            size_hint_y=None, height=dp(66), padding=[dp(12), dp(6)], spacing=dp(8)
        )
        if self.mobile:
            header.add_widget(
                button(
                    "بازگشت",
                    self.show_chat_list,
                    size_hint_x=None,
                    width=dp(65),
                    background_color=PANEL,
                )
            )
        titles = BoxLayout(orientation="vertical")
        self.heading = label("مهر", halign="right")
        self.statuslabel = label("آفلاین", font_size=dp(11))
        titles.add_widget(self.heading)
        titles.add_widget(self.statuslabel)
        header.add_widget(titles)
        header.add_widget(
            button(
                "اطلاعات",
                self.chat_info,
                size_hint_x=None,
                width=dp(75),
                background_color=PANEL,
            )
        )
        self.mainpane.add_widget(header)
        self.messagescroll = ScrollView()
        self.messagebox = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
            padding=[dp(20), dp(20)],
        )
        self.messagebox.bind(minimum_height=self.messagebox.setter("height"))
        wrap = BoxLayout(orientation="vertical", size_hint_y=None)
        wrap.add_widget(Label())
        wrap.add_widget(self.messagebox)

        def fit(*_):
            wrap.height = max(self.messagescroll.height, self.messagebox.height)

        self.messagescroll.bind(height=fit)
        self.messagebox.bind(height=fit)
        self.messagescroll.add_widget(wrap)
        self.mainpane.add_widget(self.messagescroll)
        composer = Surface(
            size_hint_y=None, height=dp(68), padding=dp(10), spacing=dp(7)
        )
        composer.add_widget(
            button(
                "+", self.attach, size_hint_x=None, width=dp(42), background_color=PANEL
            )
        )
        self.compose = field("پیام", multiline=True)
        self.compose.height = dp(48)
        self.compose.bind(
            text=lambda w, t: setattr(
                w, "halign", "right" if re.search(r"[\u0600-\u06ff]", t) else "left"
            )
        )
        composer.add_widget(self.compose)
        composer.add_widget(button("ارسال", self.send, size_hint_x=None, width=dp(70)))
        self.composer = composer
        self.mainpane.add_widget(composer)
        body.add_widget(self.mainpane)
        self.rootbox.add_widget(body)
        if self.mobile:
            self.show_chat_list()
        self.refresh()

    def show_chat_list(self):
        self.sidebar.size_hint_x = 1
        self.sidebar.width = Window.width
        self.sidebar.opacity = 1
        self.sidebar.disabled = False
        self.mainpane.size_hint_x = None
        self.mainpane.width = 0
        self.mainpane.opacity = 0
        self.mainpane.disabled = True

    def chats(self):
        d = self.engine.d
        rows = [
            (self.engine.dm_id(pid), card["body"]["name"])
            for pid, card in d["contacts"].items()
        ]
        rows.extend((gid, g["body"]["name"]) for gid, g in d["groups"].items())
        return rows

    def refresh_sidebar(self):
        term = self.search.text.lower()
        now = time.time()
        rows = self.chats()
        summary = []
        for cid, name in rows:
            last = next(
                (m for m in reversed(self.engine.d["messages"].get(cid, [])) if m["expires"] > now),
                None,
            )
            group = self.engine.d["groups"].get(cid)
            summary.append((cid, name, last["id"] if last else None,
                            len(group["body"]["members"]) if group else 0))
        signature = (self.chat, term, tuple(summary))
        if signature == self._sidebar_signature:
            return
        self._sidebar_signature = signature
        self.chatlist.clear_widgets()

        def recent(cid):
            return max(
                (
                    m["created"]
                    for m in self.engine.d["messages"].get(cid, [])
                    if m["expires"] > time.time()
                ),
                default=0,
            )

        for cid, name in sorted(
            rows, key=lambda row: recent(row[0]), reverse=True
        ):
            if term and term not in name.lower():
                continue
            history = [
                m
                for m in self.engine.d["messages"].get(cid, [])
                if m["expires"] > time.time()
            ]
            last = history[-1] if history else None
            preview = (
                (
                    last.get("text", "")
                    if last["kind"] != "file"
                    else "فایل: " + last.get("filename", "")
                )
                if last
                else ""
            )
            if not last and cid in self.engine.d["groups"]:
                preview = (
                    str(len(self.engine.d["groups"][cid]["body"]["members"])) + " عضو"
                )
            row = ChatRow(
                size_hint_y=None,
                height=dp(76),
                padding=dp(10),
                spacing=dp(10),
                color=(0.20, 0.40, 0.56, 1) if cid == self.chat else PANEL,
            )
            row.bind(on_release=lambda _, c=cid: self.select(c))
            row.add_widget(Avatar(name, cid, pos_hint={"center_y": 0.5}))
            column = BoxLayout(orientation="vertical", spacing=dp(3))
            title = label(name, halign="right", shorten=True, shorten_from="right")
            subtitle = label(
                preview.replace("\n", " "),
                halign="right",
                font_size=dp(12),
                shorten=True,
                shorten_from="right",
            )
            subtitle.color = (0.61, 0.69, 0.75, 1)
            for item in (title, subtitle):
                item.bind(
                    size=lambda widget, value: setattr(widget, "text_size", value)
                )
                column.add_widget(item)
            row.add_widget(column)
            if last:
                stamp = label(
                    time.strftime("%H:%M", time.localtime(last["created"])),
                    size_hint_x=None,
                    width=dp(34),
                    font_size=dp(10),
                )
                stamp.color = (0.61, 0.69, 0.75, 1)
                row.add_widget(stamp)
            self.chatlist.add_widget(row)
        if not self.chatlist.children:
            empty = wrapped_label("هنوز گفتگویی ندارید\nبا + یک مخاطب یا گروه اضافه کنید", size_hint_y=None, height=dp(140), font_size=dp(14))
            empty.color = (0.58, 0.68, 0.77, 1)
            self.chatlist.add_widget(empty)

    def select(self, cid):
        if cid != self.chat:
            self.remember_draft()
            with self.engine.lock:
                self.compose.text = self.engine.d.get("drafts", {}).get(cid, "")
        self.chat = cid
        self._view_signature = None
        self.view_limit = 100
        if self.mobile:
            self.sidebar.size_hint_x = None
            self.sidebar.width = 0
            self.sidebar.opacity = 0
            self.sidebar.disabled = True
            self.mainpane.size_hint_x = 1
            self.mainpane.opacity = 1
            self.mainpane.disabled = False
        self.refresh()

    def remember_draft(self):
        if self.engine and self.chat and hasattr(self, "compose"):
            with self.engine.transaction():
                drafts = self.engine.d.setdefault("drafts", {})
                if self.compose.text:
                    drafts[self.chat] = self.compose.text
                else:
                    drafts.pop(self.chat, None)

    def refresh(self):
        if not self.engine or not hasattr(self, "messagebox"):
            return
        with self.engine.lock:
            self.statuslabel.text = fa(self.engine.status)
            self.composer.disabled = not bool(self.chat)
            self.refresh_sidebar()
            self.heading.text = fa(dict(self.chats()).get(self.chat, "مهر"))
            messages = [
                m
                for m in self.engine.d["messages"].get(self.chat, [])
                if m["expires"] > time.time()
            ]
            signature = (
                self.chat,
                self.view_limit,
                tuple((m["id"], m["state"]) for m in messages),
            )
            if signature == self._view_signature:
                return
            at_bottom = (
                self.messagescroll.scroll_y < 0.1 or self._view_signature is None
            )
            self._view_signature = signature
            self.messagebox.clear_widgets()
            if len(messages) > self.view_limit:

                def more():
                    self.view_limit += 100
                    self._view_signature = None
                    self.refresh()

                self.messagebox.add_widget(button("پیام‌های قبلی", more))
            available = max(
                dp(240), Window.width - (0 if self.mobile else dp(348)) - dp(60)
            )
            previous_day = None
            for m in messages[-self.view_limit :]:
                day = time.strftime("%Y/%m/%d", time.localtime(m["created"]))
                if day != previous_day:
                    date_row = AnchorLayout(size_hint_y=None, height=dp(36))
                    chip = Surface(size_hint=(None, None), size=(dp(120), dp(28)), color=(0.13, 0.20, 0.26, 1))
                    chip.add_widget(label(day, font_size=dp(11)))
                    date_row.add_widget(chip)
                    self.messagebox.add_widget(date_row)
                    previous_day = day
                own = m["author"] == self.engine.me
                text = (
                    m.get("text", "")
                    if m["kind"] != "file"
                    else "فایل: " + m.get("filename", "")
                )
                max_chars = max(18, min(70, int(available * 0.75 / dp(9))))
                wrapped = "\n".join(
                    "\n".join(
                        textwrap.wrap(line, width=max_chars, replace_whitespace=False)
                        or [""]
                    )
                    for line in text.split("\n")
                )
                height = dp(57 + 24 * max(1, len(wrapped.split("\n"))))
                width = min(
                    available * 0.82,
                    max(
                        dp(190),
                        dp(
                            28
                            + min(
                                max_chars,
                                max((len(x) for x in wrapped.split("\n")), default=1),
                            )
                            * 9
                        ),
                    ),
                )
                line = BoxLayout(size_hint_y=None, height=height, spacing=dp(5))
                if own:
                    line.add_widget(Label())
                bubble = Surface(
                    orientation="vertical",
                    padding=[dp(12), dp(7)],
                    size_hint_x=None,
                    width=width,
                    color=(0.16, 0.32, 0.43, 1) if own else (0.13, 0.19, 0.25, 1),
                )
                if self.chat in self.engine.d["groups"]:
                    bubble.add_widget(
                        label(
                            self.engine.peer_card(m["author"])["body"]["name"],
                            font_size=dp(11),
                            size_hint_y=None,
                            height=dp(17),
                        )
                    )
                    line.height += dp(17)
                display = label(wrapped, halign="right", valign="middle")
                display.bind(size=lambda w, v: setattr(w, "text_size", v))
                bubble.add_widget(display)
                footer = BoxLayout(size_hint_y=None, height=dp(23))
                stamp = time.strftime("%H:%M", time.localtime(m["created"]))
                footer.add_widget(
                    label(stamp + "  " + (m["state"] if own else ""), font_size=dp(10))
                )
                menu = button(
                    "...",
                    lambda mid=m["id"]: self.message_menu(mid),
                    size_hint_x=None,
                    width=dp(32),
                    background_color=(0, 0, 0, 0),
                )
                menu.height = dp(23)
                footer.add_widget(menu)
                bubble.add_widget(footer)
                line.add_widget(bubble)
                if not own:
                    line.add_widget(Label())
                self.messagebox.add_widget(line)
            if not self.chat:
                self.messagebox.add_widget(
                    wrapped_label("گفتگو از همین‌جا شروع می‌شود\nیک مخاطب انتخاب کنید یا با + گفتگوی تازه بسازید", size_hint_y=None, height=dp(150))
                )
            if at_bottom:
                Clock.schedule_once(
                    lambda *_: setattr(self.messagescroll, "scroll_y", 0), 0.05
                )

    def send(self):
        if not self.chat or not self.compose.text.strip():
            return

        def action():
            with self.engine.transaction():
                self.engine.send(self.chat, self.compose.text)
                self.engine.d.setdefault("drafts", {}).pop(self.chat, None)
            self.compose.text = ""
            self.refresh()

        self.guarded(action)

    def main_menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        pop = self.dialog("منو", box)
        for title, fn in [
            ("حساب کاربری", self.profile_dialog),
            ("سرورها", self.settings),
            ("کارت هویت من", self.my_card),
            ("تغییر رمز", self.password_dialog),
            ("ذخیره پشتیبان", self.backup_dialog),
            ("قفل", self.lock_account),
        ]:
            box.add_widget(button(title, lambda f=fn: (pop.dismiss(), f())))
        box.add_widget(button("بستن", pop.dismiss))

    def new_menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        pop = self.dialog("گفتگوی جدید", box)
        box.add_widget(
            button("مخاطب جدید", lambda: (pop.dismiss(), self.contact_dialog()))
        )
        box.add_widget(
            button("گروه جدید", lambda: (pop.dismiss(), self.group_dialog()))
        )
        box.add_widget(button("بستن", pop.dismiss))

    def profile_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        username, name = field("نام کاربری"), field("نام نمایشی")
        username.text = self.engine.identity["username"]
        name.text = self.engine.identity["name"]
        box.add_widget(username)
        box.add_widget(name)
        pop = self.dialog("حساب کاربری", box)

        def save():
            self.engine.update_profile(username.text, name.text)
            pop.dismiss()
            self.refresh()

        box.add_widget(button("ذخیره", lambda: self.guarded(save)))
        box.add_widget(button("بستن", pop.dismiss))

    def password_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        old, new, again = (
            field("رمز فعلی", password=True),
            field("رمز جدید", password=True),
            field("تکرار رمز جدید", password=True),
        )
        for w in (old, new, again):
            box.add_widget(w)
        pop = self.dialog("تغییر رمز", box)

        def change():
            from .crypto import derive
            import hmac

            if not hmac.compare_digest(
                derive(old.text, self.engine.vault.salt), self.engine.vault.key
            ):
                raise ValueError("رمز فعلی درست نیست")
            if new.text != again.text:
                raise ValueError("تکرار رمز مطابقت ندارد")
            with self.engine.lock:
                self.engine.vault.change_password(new.text)
            old.text = new.text = again.text = ""
            pop.dismiss()
            self.error("رمز تغییر کرد؛ یک پشتیبان تازه ذخیره کنید")

        box.add_widget(button("ذخیره", lambda: self.guarded(change)))
        box.add_widget(button("بستن", pop.dismiss))

    def chat_info(self):
        if not self.chat:
            return
        outer = BoxLayout(orientation="vertical")
        view = ScrollView()
        box = BoxLayout(
            orientation="vertical", spacing=dp(10), padding=dp(12), size_hint_y=None
        )
        box.bind(minimum_height=box.setter("height"))
        view.add_widget(box)
        outer.add_widget(view)
        pop = self.dialog("اطلاعات گفتگو", outer)
        box.add_widget(
            label("حذف خودکار پیام‌های جدید", size_hint_y=None, height=dp(40))
        )
        chat = self.chat
        current_ttl = self.engine.d.get("chat_ttl", {}).get(
            chat, self.engine.d.get("ttl", 86400)
        )
        for title, seconds in [
            ("۱ ساعت", 3600),
            ("۱ روز", 86400),
            ("۷ روز", 604800),
            ("۳۰ روز", 2592000),
        ]:

            def ttl(value=seconds):
                with self.engine.transaction():
                    self.engine.d.setdefault("chat_ttl", {})[chat] = value
                pop.dismiss()

            box.add_widget(button(title + (" ✓" if current_ttl == seconds else ""), ttl))
        if chat in self.engine.d["groups"]:
            group = self.engine.d["groups"][chat]["body"]
            for peer in group["members"]:
                box.add_widget(
                    label(
                        self.engine.peer_card(peer)["body"]["name"],
                        size_hint_y=None,
                        height=dp(25),
                    )
                )
            if group["owner"] == self.engine.me:
                box.add_widget(
                    button(
                        "ویرایش گروه", lambda: (pop.dismiss(), self.group_dialog(chat))
                    )
                )
        else:
            peer = next(
                (p for p in self.engine.d["contacts"] if self.engine.dm_id(p) == chat),
                None,
            )
            if peer:
                box.add_widget(
                    button(
                        "تازه‌سازی نشست",
                        lambda: self.guarded(
                            lambda: (self.engine.reset_session(peer), pop.dismiss())
                        ),
                    )
                )
        box.add_widget(button("بستن", pop.dismiss))

    def settings(self):
        if self.deployment:
            box = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(16))
            box.add_widget(label("مهر · " + __version__))
            box.add_widget(label("TLS + Noise NK"))
            box.add_widget(label("SSL فعال"))
            pop = self.dialog("اطلاعات اتصال", box)
            box.add_widget(button("بستن", pop.dismiss))
            return
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        scroll = ScrollView()
        rows = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        rows.bind(minimum_height=rows.setter("height"))
        scroll.add_widget(rows)
        box.add_widget(scroll)
        fields = []

        def add_server(value=None):
            if len(fields) >= 5:
                return
            value = value or {"host": "", "port": 8787, "pin": ""}
            panel = Surface(
                orientation="vertical",
                size_hint_y=None,
                height=dp(360),
                padding=dp(8),
                spacing=dp(5),
            )
            top = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(5))
            host, port, pin = (
                field("IP یا دامنه"),
                field("پورت"),
                field("کلید عمومی سرور"),
            )
            host.text = value["host"]
            port.text = str(value["port"])
            pin.text = value["pin"]
            port.size_hint_x = 0.3
            top.add_widget(host)
            top.add_widget(port)
            panel.add_widget(top)
            panel.add_widget(pin)
            transport = Spinner(text=value.get("transport", "noise"), values=("tls", "noise"), size_hint_y=None, height=dp(44))
            ca = field("گواهی CA (PEM)", multiline=True)
            ca.text = value.get("ca", "")
            panel.add_widget(transport)
            panel.add_widget(ca)
            entry = (host, port, pin, panel, transport, ca)
            fields.append(entry)

            def remove():
                fields.remove(entry)
                rows.remove_widget(panel)

            panel.add_widget(button("حذف", remove))
            rows.add_widget(panel)

        for value in self.engine.d["relays"] or [None]:
            add_server(value)
        box.add_widget(button("افزودن سرور", add_server))
        pop = self.dialog("سرورها", box)

        def save():
            self.engine.configure_relays(
                [
                    {"host": h.text.strip(), "port": int(p.text), "pin": k.text.strip(), "transport": t.text, "ca": c.text.strip()}
                    for h, p, k, _, t, c in fields
                ]
            )
            pop.dismiss()

        box.add_widget(button("ذخیره", lambda: self.guarded(save)))
        box.add_widget(button("بستن", pop.dismiss))

    def my_card(self):
        card = self.engine.card
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        fingerprint = field("اثر انگشت", multiline=True)
        fingerprint.text = card["body"]["id"]
        data = field("کارت هویت", multiline=True)
        data.text = json.dumps(card, ensure_ascii=False)
        box.add_widget(label("اثر انگشت را از مسیر مطمئن به مخاطب بدهید"))
        box.add_widget(fingerprint)
        box.add_widget(data)
        pop = self.dialog("کارت هویت", box)
        box.add_widget(
            button(
                "ذخیره کارت",
                lambda: self.choose_document(
                    "save",
                    "identity.json",
                    lambda f: f.write(json.dumps(card, ensure_ascii=False).encode()),
                ),
            )
        )
        box.add_widget(button("بستن", pop.dismiss))

    def contact_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        card = field("کارت هویت مخاطب", multiline=True)
        fp = field("اثر انگشت تأییدشده", multiline=True)
        username = field("نام کاربری")
        box.add_widget(username)

        def lookup():
            value = username.text.strip()
            self.engine.lookup(value)
            deadline = time.monotonic() + 15

            def check(*_):
                if not self.engine:
                    return False
                result = self.engine.d["lookup_results"].pop(value, None)
                if result is not None:
                    if result.get("card"):
                        card.text = json.dumps(result["card"], ensure_ascii=False)
                    else:
                        self.error("کاربر آنلاین پیدا نشد؛ کارت هویت را وارد کنید")
                    return False
                return time.monotonic() < deadline

            Clock.schedule_interval(check, 0.2)

        box.add_widget(button("جستجو", lookup))
        box.add_widget(card)
        box.add_widget(fp)
        pop = self.dialog("مخاطب جدید", box)

        def load(f):
            raw = f.read(64 * 1024).decode()
            Clock.schedule_once(lambda *_: setattr(card, "text", raw))

        box.add_widget(
            button(
                "بازکردن کارت",
                lambda: self.choose_document("open", "identity.json", load),
            )
        )

        def add():
            pid = self.engine.add_contact(card.text, fp.text)
            pop.dismiss()
            self.select(self.engine.dm_id(pid))

        box.add_widget(button("افزودن", lambda: self.guarded(add)))
        box.add_widget(button("بستن", pop.dismiss))

    def group_dialog(self, edit_chat=None):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        name = field("نام گروه")
        current = self.engine.d["groups"][edit_chat]["body"] if edit_chat else None
        if current:
            name.text = current["name"]
        box.add_widget(name)
        view = ScrollView()
        rows = BoxLayout(orientation="vertical", size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))
        chosen = {}
        for pid, card in self.engine.d["contacts"].items():
            row = BoxLayout(size_hint_y=None, height=dp(44))
            row.add_widget(label(card["body"]["name"]))
            checkbox = CheckBox(size_hint_x=0.2)
            if current:
                checkbox.active = pid in current["members"]
            chosen[pid] = checkbox
            row.add_widget(checkbox)
            rows.add_widget(row)
        view.add_widget(rows)
        box.add_widget(view)
        pop = self.dialog("ویرایش گروه" if edit_chat else "گروه جدید", box)

        def create():
            members = [p for p, c in chosen.items() if c.active]
            if edit_chat:
                self.engine.update_group(edit_chat, name.text, members)
                cid = edit_chat
            else:
                cid = self.engine.create_group(name.text, members)
            pop.dismiss()
            self.select(cid)

        box.add_widget(button("ساخت گروه", lambda: self.guarded(create)))
        box.add_widget(button("بستن", pop.dismiss))

    def message_menu(self, mid):
        chat = self.chat
        message = next(m for m in self.engine.d["messages"][chat] if m["id"] == mid)
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        pop = self.dialog("پیام", box)

        def delete():
            self.engine.delete(chat, mid)
            pop.dismiss()
            self.refresh()

        if chat not in self.engine.d["groups"] or message["author"] == self.engine.me:
            box.add_widget(button("حذف برای همه", lambda: self.guarded(delete)))
        if message["kind"] == "file":
            engine = self.engine

            def save_file(stream):
                if self.engine is not engine:
                    raise ValueError("حساب قفل شده است")
                # Recheck at the time the picker returns, not when the menu opened.
                with engine.lock:
                    stream.write(engine.read_file(chat, mid))

            box.add_widget(
                button(
                    "ذخیره فایل",
                    lambda: self.choose_document(
                        "save",
                        Path(message["filename"]).name,
                        save_file,
                    ),
                )
            )
        box.add_widget(button("بستن", pop.dismiss))

    def attach(self):
        if not self.chat:
            return
        if not self.engine.files_enabled:
            self.error("ارسال فایل غیرفعال است")
            return
        chat = self.chat

        def load(f):
            raw = f.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("حداکثر حجم فایل ۴ مگابایت است")
            self.engine.send(
                chat,
                file_bytes=raw,
                filename=getattr(f, "display_name", None) or "file.bin",
            )

        self.choose_document("open", "file", load)

    def backup_dialog(self, on_saved=None):
        engine = self.engine

        def save(f):
            if self.engine is not engine:
                raise ValueError("حساب قفل شده است")
            with engine.lock:
                f.write(engine.vault.backup_bytes())
                f.flush()
                with engine.transaction():
                    engine.d["backup_last_at"] = int(time.time())
            if on_saved:
                on_saved()

        self.choose_document("save", "mehr-backup.mcv", save)

    def restore_dialog(self):
        if self.vault_path.exists():
            self.error("حساب موجود است؛ بازیابی روی حساب موجود انجام نمی‌شود")
            return

        def load(f):
            raw = f.read(MAX_BACKUP_BYTES + 1)
            if len(raw) > MAX_BACKUP_BYTES:
                raise ValueError("حداکثر حجم پشتیبان ۱ گیگابایت است")
            box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
            pw = field("رمز پشتیبان", password=True)
            box.add_widget(pw)
            pop = self.dialog("بازیابی پشتیبان", box)

            def restore():
                vault = Vault.restore_bytes(raw, self.vault_path, pw.text)
                pw.text = ""
                pop.dismiss()
                self.enter(vault)

            box.add_widget(button("بازیابی", lambda: self.guarded(restore)))

        self.choose_document("open", "mehr-backup.mcv", load)

    def choose_document(self, mode, name, callback):
        try:
            name = safe_filename(name)
        except ValueError:
            name = "file.bin"
        if platform == "android":
            from jnius import autoclass
            from android import activity

            Intent = autoclass("android.content.Intent")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            current = PythonActivity.mActivity
            code = 9021
            self._picking_document = True

            def result(request_code, result_code, intent):
                if request_code != code:
                    return
                activity.unbind(on_activity_result=result)
                self._picking_document = False
                if result_code != -1 or intent is None:
                    return
                uri = intent.getData()

                def process(*_):
                    def execute():
                        descriptor = current.getContentResolver().openFileDescriptor(
                            uri, "w" if mode == "save" else "r"
                        )
                        try:
                            fd = os.dup(descriptor.getFd())
                            with os.fdopen(
                                fd, "wb" if mode == "save" else "rb"
                            ) as stream:
                                if mode == "open":
                                    cursor = current.getContentResolver().query(
                                        uri, None, None, None, None
                                    )
                                    if cursor is not None:
                                        try:
                                            if cursor.moveToFirst():
                                                col = cursor.getColumnIndex(
                                                    "_display_name"
                                                )
                                                if col >= 0:
                                                    stream.display_name = str(
                                                        cursor.getString(col)
                                                    )
                                        finally:
                                            cursor.close()
                                callback(stream)
                        finally:
                            descriptor.close()

                    self.guarded(execute)

                Clock.schedule_once(process)

            activity.bind(on_activity_result=result)
            intent = Intent(
                Intent.ACTION_CREATE_DOCUMENT
                if mode == "save"
                else Intent.ACTION_OPEN_DOCUMENT
            )
            intent.addCategory(Intent.CATEGORY_OPENABLE)
            intent.setType("application/octet-stream" if mode == "save" else "*/*")
            if mode == "save":
                intent.putExtra(Intent.EXTRA_TITLE, name)
            try:
                current.startActivityForResult(intent, code)
            except Exception:
                self._picking_document = False
                activity.unbind(on_activity_result=result)
                raise
            return
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        path = field("مسیر کامل فایل")
        path.text = str(Path.home() / name) if mode == "save" else ""
        box.add_widget(path)
        pop = self.dialog("ذخیره فایل" if mode == "save" else "بازکردن فایل", box)

        def execute():
            chosen = Path(path.text).expanduser()
            stream = chosen.open("xb" if mode == "save" else "rb")
            try:
                with stream:
                    if mode == "save" and os.name != "nt":
                        os.fchmod(stream.fileno(), 0o600)
                    stream.display_name = chosen.name
                    callback(stream)
            except BaseException:
                if mode == "save":
                    chosen.unlink(missing_ok=True)
                raise
            pop.dismiss()

        box.add_widget(button("تأیید", lambda: self.guarded(execute)))
        box.add_widget(button("بستن", pop.dismiss))

    def activity(self):
        self.last_activity = time.monotonic()

    def lock_account(self):
        if not self.engine:
            return
        engine = self.engine
        self.remember_draft()
        engine.stop()
        if hasattr(engine, "thread"):
            engine.thread.join(timeout=5)
        if hasattr(engine, "thread") and engine.thread.is_alive():
            self.error("در حال بستن اتصال")
            return
        for popup in list(self.open_popups):
            popup.dismiss()
        with engine.lock:
            engine.vault.close()
        self.engine = None
        self.chat = None
        self.compose.text = ""
        self.unlock_screen()

    def tick(self):
        if self.engine:
            if time.monotonic() - self.last_activity > 300:
                self.lock_account()
            else:
                self.engine.prune()

    def on_pause(self):
        if not getattr(self, "_picking_document", False):
            self.lock_account()
        return True

    def on_resume(self):
        self.tick()

    def on_stop(self):
        if self.engine:
            self.lock_account()


def main():
    MehrApp().run()


if __name__ == "__main__":
    main()
