import json
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
from kivy.uix.textinput import TextInput
from kivy.utils import platform
from .vault import Vault
from .client import Engine, safe_filename
from .crypto import public_card, check_card

ROOT = Path(__file__).resolve().parent.parent
FONT = str(ROOT / "assets" / "Vazirmatn-Regular.ttf")
BG = (0.055, 0.09, 0.13, 1)
PANEL = (0.09, 0.13, 0.18, 1)
BLUE = (0.18, 0.56, 0.79, 1)
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
    pass


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


def button(text, callback, **kw):
    color = kw.pop("background_color", BLUE)
    b = Button(
        text=fa(text),
        font_name=FONT,
        font_size=dp(15),
        background_normal="",
        background_color=color,
        size_hint_y=None,
        height=dp(44),
        **kw
    )
    b.bind(on_release=lambda *_: callback())
    return b


class PersianInput(TextInput):
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
        padding=[dp(12), dp(12)],
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
        self.unlock_screen()
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
        box.add_widget(label(str(message)))
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

    def unlock_screen(self):
        self.rootbox.clear_widgets()
        wrap = BoxLayout(
            orientation="vertical",
            padding=[dp(30), dp(30)],
            spacing=dp(14),
            size_hint=(1, None),
            height=dp(500),
        )
        wrap.add_widget(label("مهر", font_size=dp(38), size_hint_y=None, height=dp(70)))
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
        self.rootbox.add_widget(wrap)

    def unlock(self):
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
        notice = label(text, halign="right", valign="middle")
        notice.bind(size=lambda w, value: setattr(w, "text_size", value))
        box.add_widget(notice)
        pop = self.dialog("پشتیبان حساب", box)
        box.add_widget(button("ذخیره پشتیبان", lambda: (pop.dismiss(), self.backup_dialog())))
        box.add_widget(button("بعداً", pop.dismiss))

    def shell(self):
        self.rootbox.clear_widgets()
        self.mobile = Window.width < dp(720)
        self.view_limit = 100
        self._view_signature = None
        body = BoxLayout(spacing=dp(1))
        self.sidebar = Surface(
            orientation="vertical",
            size_hint_x=None,
            width=dp(320),
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
        toolbar.add_widget(label("گفتگوها"))
        toolbar.add_widget(button("+", self.new_menu, size_hint_x=None, width=dp(44)))
        self.sidebar.add_widget(toolbar)
        self.search = field("جستجو")
        self.search.bind(text=lambda *_: self.refresh_sidebar())
        self.sidebar.add_widget(self.search)
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
        self.mainpane.size_hint_x = 0
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
        self.chatlist.clear_widgets()
        term = self.search.text.lower()

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
            self.chats(), key=lambda row: recent(row[0]), reverse=True
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
                color=(0.16, 0.32, 0.43, 1) if cid == self.chat else PANEL,
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

    def select(self, cid):
        if cid != self.chat:
            self.remember_draft()
            with self.engine.lock:
                self.compose.text = self.engine.d.get("drafts", {}).get(cid, "")
        self.chat = cid
        self._view_signature = None
        self.view_limit = 100
        if self.mobile:
            self.sidebar.size_hint_x = 0
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
                dp(240), Window.width - (0 if self.mobile else dp(320)) - dp(60)
            )
            for m in messages[-self.view_limit :]:
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
                    color=(0.16, 0.33, 0.40, 1) if own else PANEL,
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
                    label("یک گفتگو انتخاب کنید", size_hint_y=None, height=dp(150))
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
                height=dp(167),
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
            entry = (host, port, pin, panel)
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
                    {"host": h.text.strip(), "port": int(p.text), "pin": k.text.strip()}
                    for h, p, k, _ in fields
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
            self.chat = self.engine.dm_id(pid)
            pop.dismiss()
            self.refresh()

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
                self.chat = edit_chat
            else:
                self.chat = self.engine.create_group(name.text, members)
            pop.dismiss()
            self.refresh()

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

    def backup_dialog(self):
        engine = self.engine

        def save(f):
            if self.engine is not engine:
                raise ValueError("حساب قفل شده است")
            with engine.lock:
                engine.vault.save()
                f.write(self.vault_path.read_bytes())
                f.flush()
                with engine.transaction():
                    engine.d["backup_last_at"] = int(time.time())

        self.choose_document("save", "mehr-backup.mcv", save)

    def restore_dialog(self):
        if self.vault_path.exists():
            self.error("حساب موجود است؛ بازیابی روی حساب موجود انجام نمی‌شود")
            return

        def load(f):
            raw = f.read(128 * 1024 * 1024 + 1)
            if len(raw) > 128 * 1024 * 1024:
                raise ValueError("حجم پشتیبان بیش از حد مجاز است")
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
            with Path(path.text).expanduser().open(
                "xb" if mode == "save" else "rb"
            ) as stream:
                stream.display_name = Path(path.text).name
                callback(stream)
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
