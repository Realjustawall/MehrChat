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
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, InstructionGroup, Line, Ellipse
from kivy.uix.floatlayout import FloatLayout
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
from .vault import Vault, MAX_BACKUP_BYTES
from .client import Engine, safe_filename
from .crypto import public_card, check_card
from .i18n import EN, tr, language, alignment, load_language, save_language
from .privacy import protect_android_screen, protect_windows_screen
from .deployment import DEFAULT_RELAY, read_profile, validate_relay, write_json
from .wire import preflight

ROOT = Path(__file__).resolve().parent.parent
FONT = str(ROOT / "assets" / "Vazirmatn-Regular.ttf")
BG = (0.055, 0.086, 0.12, 1)
PANEL = (0.09, 0.125, 0.17, 1)
BLUE = (0.22, 0.61, 0.85, 1)
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
        kw.setdefault("size", (dp(48), dp(48)))
        palette = [
            (0.25, 0.56, 0.69, 1),
            (0.43, 0.42, 0.69, 1),
            (0.31, 0.59, 0.48, 1),
            (0.70, 0.45, 0.34, 1),
        ]
        super().__init__(
            color=palette[int(identity[:2], 16) % len(palette)],
            size_hint=(None, None),
            **kw
        )
        self.rect.radius = [dp(24)]
        self.add_widget(label(name.strip()[:1], font_size=dp(23)))


def label(text="", **kw):
    kw.setdefault("font_size", dp(16))
    return Label(text=fa(text), font_name=FONT, color=TEXT, **kw)


def wrapped_label(text, **kw):
    kw.setdefault('size_hint_y', None)
    widget = label("", halign=alignment(), valign="middle", **kw)
    logical = [str(text)]

    def fit(*_):
        # Wrap logical Persian before bidi shaping; wrapping the visual string
        # reverses sentence fragments on narrow screens.
        columns = max(8, int(widget.width / (widget.font_size * 0.65)))
        lines = ["\n".join(textwrap.wrap(line, columns) or [""]) for line in logical[0].split("\n")]
        widget.text_size = (widget.width, None)
        widget.text = fa("\n".join(lines))

    def update(value):
        logical[0] = str(value)
        fit()
    widget.update_text = update
    widget.bind(width=fit, font_size=fit, texture_size=lambda w, size: setattr(w, 'height', max(dp(28),size[1]+dp(8))))
    fit()
    return widget


def button(text, callback, **kw):
    color = kw.pop("background_color", BLUE)
    icon = kw.pop('icon', None)
    kw.setdefault('height', dp(44))
    kw.setdefault('size_hint_y', None)
    b = Button(
        text=fa(text),
        font_name=FONT,
        font_size=dp(15),
        background_normal="",
        background_color=(0, 0, 0, 0),
        **kw
    )
    with b.canvas.before:
        fill = Color(*color)
        shape = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(28) if icon in ('send','compose') else dp(14)])
    def redraw(*_):
        shape.pos, shape.size = b.pos, b.size
        fill.rgba = tuple(c * 0.82 for c in color[:3]) + (color[3],) if b.state == "down" else color
    b.bind(pos=redraw, size=redraw, state=redraw)
    if icon:
        b.color = (1, 1, 1, 0)
        group = InstructionGroup()
        b.canvas.after.add(group)
        def draw_icon(*_):
            group.clear()
            group.add(Color(0.88, 0.94, 0.98, 1))
            x, y, s = b.center_x, b.center_y, dp(10)
            def stroke(points, close=False):
                group.add(Line(points=points, width=dp(1.2), close=close))
            if icon=='menu':
                for dy in (-s*0.6, 0, s*0.6): stroke([x-s,y+dy,x+s,y+dy])
            elif icon=='back':
                stroke([x+s*0.3,y+s,x-s*0.7,y,x+s*0.3,y-s])
            elif icon=='send':
                stroke([x-s,y+s,x+s,y,x-s,y-s,x-s*0.45,y,x-s,y+s], True)
                stroke([x-s*0.45,y,x+s,y])
            elif icon=='attach':
                stroke([x-s*0.7,y-s*0.5,x+s*0.6,y+s*0.8,x+s,y+s*0.4,x-s*0.3,y-s,x-s*0.8,y-s*0.6,x+s*0.4,y+s*0.5])
            elif icon=='compose':
                stroke([x-s*0.8,y-s*0.8,x-s*0.55,y-s*0.1,x+s*0.65,y+s*0.85,x+s,y+s*0.5,x-s*0.15,y-s*0.7], True)
            elif icon=='info':
                group.add(Line(circle=(x,y,s),width=dp(1.2)))
                stroke([x,y-s*0.55,x,y+s*0.1])
                group.add(Ellipse(pos=(x-dp(1),y+s*0.45),size=(dp(2),dp(2))))
        b.bind(pos=draw_icon,size=draw_icon)
        draw_icon()
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
    widget = PersianInput(
        hint_text=hint,
        password=password,
        allow_copy=not password,
        keyboard_suggestions=False,
        input_type="null",
        halign=alignment(),
        multiline=multiline,
        font_name=FONT,
        font_size=dp(16),
        background_normal="",
        background_active="",
        background_color=(0, 0, 0, 0),
        foreground_color=TEXT,
        cursor_color=BLUE,
        padding=[dp(12), dp(12)],
        size_hint_y=None,
        height=dp(48) if not multiline else dp(120),
    )
    background = InstructionGroup()
    background.add(Color(0.12, 0.17, 0.22, 1))
    shape = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(18)])
    background.add(shape)
    widget.canvas.before.insert(0, background)
    def redraw(*_):
        shape.pos, shape.size = widget.pos, widget.size
    widget.bind(pos=redraw, size=redraw)
    return widget


class MehrApp(App):
    title = tr("مهر")

    def build(self):
        Window.clearcolor = BG
        self.engine = None
        self._locking = False
        self.chat = None
        self.rootbox = Surface(orientation="vertical", padding=0, spacing=0, color=BG)
        self.open_popups = []
        self.last_activity = time.monotonic()
        Window.bind(
            on_touch_down=lambda *_: self.activity(),
            on_key_down=lambda *_: self.activity(),
        )
        # Windows can dispatch on_resize before its size properties and the
        # root widget are updated. Re-evaluate after the layout tick as well.
        self._resize_trigger = Clock.create_trigger(self.resize_layout, 0)
        Window.bind(on_resize=lambda *_: self._resize_trigger(), size=lambda *_: self._resize_trigger())
        self.rootbox.bind(size=lambda *_: self._resize_trigger())
        self.vault_path = self.data_path()
        self.language_path = self.vault_path.parent / "language.json"
        load_language(self.language_path)
        self.title = tr("مهر")
        self.screen_protected = platform != "android"
        self.screen_protection_done = platform != "android"
        self.login_failures = 0
        self.login_retry_at = 0
        self.connection_path = self.vault_path.parent / 'connection.json'
        profile_path = ROOT / 'assets/client-profile.json'
        self.dedicated = read_profile(profile_path) if profile_path.exists() and os.environ.get('MEHRCHAT_SMOKE_TEST') != 'flow' else None
        self.connection_ready = os.environ.get('MEHRCHAT_SMOKE_TEST') == 'flow'
        self.selected_relay = dict(self.dedicated['relay']) if self.dedicated else dict(DEFAULT_RELAY)
        if not self.dedicated and self.connection_path.exists():
            try:
                with self.connection_path.open(encoding='utf-8') as f:
                    self.selected_relay = validate_relay(json.loads(f.read(8192)))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.unlock_screen() if self.connection_ready else self.connection_screen()
        if platform == "android":
            try:
                protect_android_screen(lambda ok: Clock.schedule_once(lambda *_: self.screen_protection_result(ok)))
            except Exception:
                self.screen_protection_result(False)
        elif platform == "win":
            Clock.schedule_once(lambda *_: protect_windows_screen(), 0.2)
        Clock.schedule_interval(lambda *_: self.tick(), 5)
        return self.rootbox

    def screen_protection_result(self, ok):
        self.screen_protection_done = True
        self.screen_protected = ok
        if hasattr(self, 'loginbutton'):
            self.loginbutton.disabled = not ok
        if not ok:
            self.error(tr("حفاظت صفحه فعال نشد؛ حساب باز نمی‌شود"))

    def change_language(self):
        self.remember_draft()
        save_language(self.language_path, "en" if language() == "fa" else "fa")
        self.title = tr("مهر")
        for popup in list(self.open_popups):
            popup.dismiss()
        if self.engine:
            chat = self.chat
            self.shell()
            if chat:
                self.select(chat)
                self.compose.text = self.engine.d.get("drafts", {}).get(chat, "")
        else:
            self.unlock_screen() if self.connection_ready else self.connection_screen()

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
        elif self.engine and hasattr(self, "body"):
            self.layout_panes()
            self._view_signature = None
            self.refresh()

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
        popup.bind(on_dismiss=lambda *_: self.scrub_widgets(body))
        popup.bind(
            on_dismiss=lambda *_: (
                self.open_popups.remove(popup) if popup in self.open_popups else None
            )
        )
        popup.open()
        return popup

    @staticmethod
    def scrub_widgets(root):
        for widget in root.walk():
            if isinstance(widget, TextInput):
                widget.text = ""
                widget.reset_undo()
            elif isinstance(widget, Label):
                widget.text = ""

    def error(self, message):
        box = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        box.add_widget(wrapped_label(tr(message)))
        pop = self.dialog(tr("پیام"), box)
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def guarded(self, fn):
        try:
            fn()
        except Exception as e:
            self.error(
                str(e)
                if isinstance(e, ValueError) and (str(e) in EN or str(e) in EN.values())
                else tr("عملیات انجام نشد؛ اطلاعات را بررسی کنید")
            )

    def connection_screen(self):
        from . import __version__
        self.rootbox.clear_widgets()
        self._connection_generation = getattr(self, '_connection_generation', 0) + 1
        generation = self._connection_generation
        outer = BoxLayout(padding=[dp(24), dp(24)])
        outer.add_widget(Label())
        scroll = ScrollView(size_hint_x=None, width=min(Window.width-dp(48), dp(440)), do_scroll_x=False)
        card = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(14), padding=[0, dp(20)])
        card.bind(minimum_height=card.setter('height'))
        card.add_widget(label(tr('مهر'), font_size=dp(42), bold=True, size_hint_y=None, height=dp(72)))
        card.add_widget(label(tr('ابتدا به سرور متصل شوید'), font_size=dp(20), size_hint_y=None, height=dp(36)))
        card.add_widget(wrapped_label(tr('اتصال پیش از ورود بررسی می‌شود؛ در این مرحله حسابی ساخته نمی‌شود')))
        self.connection_mode = self.selected_relay.get('transport', 'tls-noise')
        if not self.dedicated:
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
            self.connection_host = field(tr('IP یا دامنه'))
            self.connection_host.text = self.selected_relay['host']
            self.connection_port = field(tr('پورت'))
            self.connection_port.size_hint_x = 0.28
            self.connection_port.text = str(self.selected_relay['port'])
            row.add_widget(self.connection_host); row.add_widget(self.connection_port)
            card.add_widget(row)
            modes = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
            self.mode_tls = button('TLS + Noise', lambda: choose('tls-noise'))
            self.mode_noise = button('Noise', lambda: choose('noise'))
            modes.add_widget(self.mode_tls); modes.add_widget(self.mode_noise)
            card.add_widget(modes)
            self.connection_tls_pin = field(tr('اثر انگشت TLS برای گواهی محلی'))
            self.connection_tls_pin.text = self.selected_relay.get('tls_pin', '')
            self.connection_noise_pin = field(tr('کلید عمومی سرور'))
            self.connection_noise_pin.text = self.selected_relay.get('pin', '')
            card.add_widget(self.connection_tls_pin); card.add_widget(self.connection_noise_pin)
            card.add_widget(wrapped_label(tr('گواهی عمومی خودکار بررسی می‌شود؛ برای گواهی محلی پروفایل صادرشده توسط مدیر را وارد کنید')))
            def load_profile(stream):
                from .deployment import validate_profile
                raw = stream.read(8193)
                if len(raw)>8192: raise ValueError('Profile too large')
                self.selected_relay = dict(validate_profile(json.loads(raw))['relay'])
                self.connection_screen()
            card.add_widget(button(tr('واردکردن پروفایل سرور'), lambda: self.choose_document('open', 'client-profile.json', load_profile)))
            def choose(mode):
                self.connection_mode = mode
                self.connection_tls_pin.disabled = mode != 'tls-noise'
                if mode == 'noise': self.connection_tls_pin.text = ''
                self.connection_status.update_text('TLS + Noise' if mode == 'tls-noise' else tr('TLS غیرفعال؛ Noise فعال'))
        card.add_widget(label(__version__ + '  ·  ' + ('TLS + Noise' if self.connection_mode=='tls-noise' else 'Noise'), font_size=dp(13), size_hint_y=None, height=dp(28)))
        self.connection_status = wrapped_label(tr('آماده برای آزمایش اتصال'))
        def test_connection():
            try:
                value = dict(self.selected_relay) if self.dedicated else {
                    'host':self.connection_host.text.strip(), 'port':int(self.connection_port.text),
                    'transport':self.connection_mode, 'pin':self.connection_noise_pin.text.strip(),
                    'tls_pin':self.connection_tls_pin.text.strip()}
                validate_relay(value, complete=False)
            except (ValueError, KeyError, TypeError):
                self.connection_status.update_text(tr('مشخصات سرور معتبر نیست')); return
            self.connectbutton.disabled = True
            self.connection_status.update_text(tr('در حال بررسی اتصال امن'))
            def complete(result=None):
                if generation != self._connection_generation: return
                self.connectbutton.disabled = False
                if result is None:
                    self.connection_status.update_text(tr('اتصال ناموفق؛ آدرس، پورت و کلید اعتماد را بررسی کنید'))
                    return
                try:
                    self.selected_relay, self.server_info = result
                    if not self.dedicated: write_json(self.connection_path, self.selected_relay)
                    self.connection_ready = True
                    self.unlock_screen()
                except OSError:
                    self.connection_status.update_text(tr('ذخیره تنظیمات اتصال انجام نشد'))
            def work():
                try:
                    result = asyncio.run(preflight(value))
                except Exception:
                    result = None
                Clock.schedule_once(lambda *_: complete(result))
            threading.Thread(target=work, daemon=True).start()
        self.connectbutton = button(tr('اتصال و ادامه'), test_connection)
        column = BoxLayout(orientation='vertical', size_hint_x=None, width=scroll.width, spacing=dp(10))
        scroll.size_hint_x = 1
        scroll.add_widget(card)
        column.add_widget(scroll)
        column.add_widget(self.connection_status)
        column.add_widget(self.connectbutton)
        column.add_widget(button('English' if language()=='fa' else 'فارسی', self.change_language, background_color=PANEL))
        outer.bind(width=lambda _, width: setattr(column, 'width', max(dp(1), min(width-dp(48), dp(440)))))
        self.connection_panel = column
        outer.add_widget(column); outer.add_widget(Label())
        self.rootbox.add_widget(outer)

    def unlock_screen(self):
        if not self.connection_ready:
            self.connection_screen()
            return
        self.rootbox.clear_widgets()
        frame = BoxLayout(padding=[dp(24), dp(24)])
        frame.add_widget(Label())
        scroll = ScrollView(size_hint_x=None, width=min(Window.width-dp(48),dp(420)), do_scroll_x=False)
        wrap = BoxLayout(orientation='vertical', padding=[dp(8),dp(24)], spacing=dp(16), size_hint_y=None)
        wrap.bind(minimum_height=wrap.setter('height'))
        hero = BoxLayout(size_hint_y=None, height=dp(96))
        hero.add_widget(Label())
        hero.add_widget(button(tr('مهر'), lambda: None, icon='send', size_hint_x=None, width=dp(80), height=dp(80)))
        hero.add_widget(Label())
        wrap.add_widget(hero)
        wrap.add_widget(label(tr("مهر"), font_size=dp(36), bold=True, size_hint_y=None, height=dp(55)))
        wrap.add_widget(wrapped_label(tr('گفتگوهای شما، با کلیدهای روی دستگاه شما')))
        self.username = field(tr("نام کاربری"))
        self.displayname = field(tr("نام نمایشی"))
        if not self.vault_path.exists():
            wrap.add_widget(self.username)
            wrap.add_widget(self.displayname)
        self.password = field(tr("رمز عبور"), password=True)
        wrap.add_widget(self.password)
        self.loginbutton = button(
            tr("ورود") if self.vault_path.exists() else tr("ساخت حساب"), self.unlock
        )
        self.loginbutton.disabled = not self.screen_protected
        wrap.add_widget(self.loginbutton)
        wrap.add_widget(button(tr("بازیابی پشتیبان"), self.restore_dialog))
        wrap.add_widget(button("English" if language() == "fa" else "فارسی", self.change_language))
        if os.environ.get('MEHRCHAT_SMOKE_TEST') != 'flow':
            wrap.add_widget(label(tr('اتصال امن تأیید شد'), font_size=dp(12), size_hint_y=None, height=dp(28)))
            if not self.dedicated:
                def change_connection():
                    self.connection_ready = False
                    self.connection_screen()
                wrap.add_widget(button(tr('تغییر اتصال'),change_connection,background_color=PANEL))
        frame.bind(width=lambda _, width: setattr(scroll, 'width', max(dp(1), min(width-dp(48), dp(420)))))
        self.unlock_panel = scroll
        scroll.add_widget(wrap); frame.add_widget(scroll); frame.add_widget(Label())
        self.rootbox.add_widget(frame)

    def unlock(self):
        if not self.connection_ready:
            return
        if self.loginbutton.disabled:
            return
        if not self.screen_protected:
            self.error(tr("حفاظت صفحه فعال نشد؛ حساب باز نمی‌شود"))
            return
        if time.monotonic() < self.login_retry_at:
            self.error(tr("لطفاً پیش از تلاش دوباره کمی صبر کنید"))
            return
        pw = self.password.text
        self.password.text = ""
        self.password.reset_undo()
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
                    else tr("رمز عبور یا فایل معتبر نیست")
                )
                Clock.schedule_once(lambda _, m=message: self.unlock_failed(m))

        threading.Thread(target=work, daemon=True).start()

    def unlock_failed(self, message):
        self.login_failures += 1
        self.login_retry_at = time.monotonic() + min(60, 2 ** min(self.login_failures - 1, 6))
        self.password.text = ""
        self.loginbutton.disabled = False
        self.error(message)

    def enter(self, vault):
        if not self.screen_protected:
            vault.close()
            self.error(tr("حفاظت صفحه فعال نشد؛ حساب باز نمی‌شود"))
            return
        self.login_failures = 0
        self.login_retry_at = 0
        self._locking = False
        self.password.text = ""
        vault.acquire_lock()
        self.last_activity = time.monotonic()
        if self.selected_relay.get('pin') and os.environ.get('MEHRCHAT_SMOKE_TEST') != 'flow':
            vault.data['relays'] = [dict(self.selected_relay)]
            vault.save()
        self.engine = Engine(vault, self.dedicated['relay'] if self.dedicated else None)
        self.engine.changed = lambda: Clock.schedule_once(lambda *_: self.refresh())
        self.engine.start()
        self.shell()
        if not vault.data.get("backup_last_at"):
            self.backup_reminder()

    def backup_reminder(self):
        box = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(12))
        text = (
            tr("برای بازیابی حساب، پشتیبان رمزگذاری‌شده را خارج از برنامه ذخیره کنید.\n"
            "با حذف برنامه در اندروید، کلید داخل برنامه پاک می‌شود.\n"
            "رمز پشتیبان را نگه دارید؛ بازیابی بدون آن ممکن نیست.")
        )
        notice = wrapped_label(text)
        box.add_widget(notice)
        pop = self.dialog(tr("پشتیبان حساب"), box)
        box.add_widget(button(tr("ذخیره پشتیبان"), lambda: self.backup_dialog(on_saved=pop.dismiss)))
        if platform == "android":
            # Android deletes private app data on uninstall. Setup must not
            # silently continue after cancelling the external backup picker.
            pop.auto_dismiss = False
            box.add_widget(button(tr("قفل حساب"), self.lock_account))
        else:
            box.add_widget(button(tr("بعداً"), pop.dismiss))

    def shell(self):
        self.rootbox.clear_widgets()
        self.mobile = Window.width < dp(720)
        self.view_limit = 100
        self._view_signature = None
        self._sidebar_signature = None
        body = self.body = BoxLayout(spacing=0)
        self.mobile_view = "list"
        self.sidebar = Surface(
            orientation="vertical",
            size_hint_x=None,
            width=dp(340),
            padding=[dp(8), dp(8)],
            spacing=dp(8),
        )
        toolbar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        toolbar.add_widget(
            button(
                tr("منو"),
                self.main_menu,
                size_hint_x=None,
                width=dp(44), icon='menu',
                background_color=PANEL,
            )
        )
        toolbar.add_widget(label(tr("مهر"), bold=True, font_size=dp(23), halign=alignment()))
        self.sidebar.add_widget(toolbar)
        self.search = field(tr("جستجو"))
        self.search.height = dp(42)
        self.search.bind(text=lambda *_: self.refresh())
        self.sidebar.add_widget(self.search)
        scroll = ScrollView(bar_width=dp(2), pos_hint={'x':0,'y':0})
        self.chatlist = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(2)
        )
        self.chatlist.bind(minimum_height=self.chatlist.setter("height"))
        scroll.add_widget(self.chatlist)
        list_area = FloatLayout()
        list_area.add_widget(scroll)
        self.compose_new = button(tr('گفتگوی جدید'), self.new_menu, size_hint=(None,None), width=dp(56), height=dp(56), pos_hint={'right':0.96,'y':0.025}, icon='compose')
        list_area.add_widget(self.compose_new)
        self.sidebar.add_widget(list_area)
        body.add_widget(self.sidebar)
        self.mainpane = Surface(orientation="vertical", padding=0, spacing=0, color=BG)
        header = Surface(
            size_hint_y=None, height=dp(66), padding=[dp(12), dp(6)], spacing=dp(8)
        )
        if self.mobile:
            header.add_widget(
                button(
                    tr("بازگشت"),
                    self.show_chat_list,
                    size_hint_x=None,
                    width=dp(40), icon='back',
                    background_color=PANEL,
                )
            )
        self.chat_avatar = Avatar(tr("مهر"), self.engine.me, size=(dp(42), dp(42)), pos_hint={"center_y": 0.5})
        header.add_widget(self.chat_avatar)
        titles = BoxLayout(orientation="vertical")
        self.heading = label(tr("مهر"), halign=alignment(), bold=True, shorten=True, shorten_from="right")
        self.statuslabel = label(tr("آفلاین"), font_size=dp(11))
        for title in (self.heading, self.statuslabel):
            title.bind(size=lambda w, size: setattr(w, "text_size", size))
            title.shorten = True
        self.statuslabel.color = (0.53, 0.75, 0.87, 1)
        titles.add_widget(self.heading)
        titles.add_widget(self.statuslabel)
        header.add_widget(titles)
        header.add_widget(
            button(
                tr("اطلاعات"),
                self.chat_info,
                size_hint_x=None,
                width=dp(42), icon='info',
                background_color=PANEL,
            )
        )
        self.mainpane.add_widget(header)
        self.messagescroll = ScrollView(bar_width=dp(2))
        self.messagebox = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
            padding=[dp(10), dp(16)],
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
            size_hint_y=None, height=dp(68), padding=dp(8), spacing=dp(6)
        )
        composer.add_widget(
            button(
                "+", self.attach, size_hint_x=None, width=dp(42), background_color=BG, icon='attach'
            )
        )
        self.compose = field(tr("پیام"), multiline=True)
        self.compose.height = dp(50)
        self.compose.bind(
            text=lambda w, t: setattr(
                w, "halign", "right" if re.search(r"[\u0600-\u06ff]", t) else "left"
            )
        )
        composer.add_widget(self.compose)
        composer.add_widget(button(tr("ارسال"), self.send, size_hint_x=None, width=dp(50), icon='send'))
        self.mainpane.add_widget(composer)
        body.add_widget(self.mainpane)
        self.rootbox.add_widget(body)
        self.layout_panes()
        self.refresh()

    def layout_panes(self):
        # Invisible size_hint=0 children still keep their previous minimum width.
        # Mount only the active pane on phones so it cannot displace the other.
        self.body.clear_widgets()
        self.sidebar.opacity = self.mainpane.opacity = 1
        self.sidebar.disabled = self.mainpane.disabled = False
        if self.mobile:
            pane = self.sidebar if self.mobile_view == "list" else self.mainpane
            pane.size_hint_x = 1
            self.body.add_widget(pane)
        else:
            self.sidebar.size_hint_x = None
            self.sidebar.width = dp(340)
            self.mainpane.size_hint_x = 1
            panes = (self.mainpane, self.sidebar) if language() == "fa" else (self.sidebar, self.mainpane)
            for pane in panes:
                self.body.add_widget(pane)

    def show_chat_list(self):
        self.mobile_view = "list"
        self.layout_panes()

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
                    else tr("فایل: ") + last.get("filename", "")
                )
                if last
                else ""
            )
            if not last and cid in self.engine.d["groups"]:
                preview = (
                    str(len(self.engine.d["groups"][cid]["body"]["members"])) + tr(" عضو")
                )
            row = ChatRow(
                size_hint_y=None,
                height=dp(78),
                padding=dp(10),
                spacing=dp(10),
                color=(0.15, 0.27, 0.36, 1) if cid == self.chat and not self.mobile else PANEL,
            )
            row.bind(on_release=lambda _, c=cid: self.select(c))
            row.add_widget(Avatar(name, cid, pos_hint={"center_y": 0.5}))
            column = BoxLayout(orientation="vertical", spacing=dp(3))
            title = label(name, halign=alignment(), shorten=True, shorten_from="right", bold=True, font_size=dp(17))
            subtitle = label(
                preview.replace("\n", " "),
                halign=alignment(),
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
            if language() == "fa":
                children = list(row.children)
                row.clear_widgets()
                for child in children:
                    row.add_widget(child)
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
            self.mobile_view = "chat"
            self.layout_panes()
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
        if self._locking or not self.engine or not hasattr(self, "messagebox"):
            return
        with self.engine.lock:
            self.statuslabel.text = fa(tr(self.engine.status) + "  ·  E2EE")
            self.refresh_sidebar()
            name = dict(self.chats()).get(self.chat, tr("مهر"))
            self.heading.text = fa(name)
            self.chat_avatar.children[0].text = fa(name.strip()[:1])
            messages = [
                m
                for m in self.engine.d["messages"].get(self.chat, [])
                if m["expires"] > time.time()
            ]
            signature = (
                self.chat,
                self.view_limit,
                round(self.mainpane.width),
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

                self.messagebox.add_widget(button(tr("پیام‌های قبلی"), more))
            available = max(
                dp(180), Window.width - (0 if self.mobile else dp(340)) - dp(20)
            )
            previous_day = None
            for m in messages[-self.view_limit :]:
                day = time.strftime("%Y-%m-%d", time.localtime(m["created"]))
                if day != previous_day:
                    date_row = BoxLayout(size_hint_y=None, height=dp(34), padding=[0, dp(3)])
                    date_row.add_widget(Label())
                    chip = Surface(size_hint_x=None, width=dp(110), color=(0.12, 0.19, 0.23, 1))
                    chip.add_widget(label(day, font_size=dp(11)))
                    date_row.add_widget(chip)
                    date_row.add_widget(Label())
                    self.messagebox.add_widget(date_row)
                    previous_day = day
                own = m["author"] == self.engine.me
                text = (
                    m.get("text", "")
                    if m["kind"] != "file"
                    else tr("فایل: ") + m.get("filename", "")
                )
                max_chars = max(18, min(70, int(available * 0.75 / dp(9))))
                wrapped = "\n".join(
                    "\n".join(
                        textwrap.wrap(line, width=max_chars, replace_whitespace=False)
                        or [""]
                    )
                    for line in text.split("\n")
                )
                height = dp(34 + 23 * max(1, len(wrapped.split("\n"))))
                width = min(
                    available * 0.82,
                    max(
                        dp(125),
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
                    color=(0.16, 0.31, 0.38, 1) if own else (0.13, 0.18, 0.23, 1),
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
                display = label(wrapped, halign="right" if re.search(r"[\u0600-\u06ff]", text) else "left", valign="middle")
                display.bind(size=lambda w, v: setattr(w, "text_size", v))
                bubble.add_widget(display)
                footer = BoxLayout(size_hint_y=None, height=dp(23))
                stamp = time.strftime("%H:%M", time.localtime(m["created"]))
                state = ("✓✓" if m["state"] == "تحویل شد" else "✓" if m["state"] == "به سرور رسید" else "…") if own else ""
                footer.add_widget(label(stamp + "  " + state, font_size=dp(10)))
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
                    label(tr("یک گفتگو انتخاب کنید"), size_hint_y=None, height=dp(150))
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
        pop = self.dialog(tr("منو"), box)
        for title, fn in [
            (tr("حساب کاربری"), self.profile_dialog),
            (tr("سرورها"), self.settings),
            (tr("کارت هویت من"), self.my_card),
            (tr("تغییر رمز"), self.password_dialog),
            (tr("ذخیره پشتیبان"), self.backup_dialog),
            (tr("قفل"), self.lock_account),
            (tr("امنیت و حریم خصوصی"), self.privacy_dialog),
            ("English" if language() == "fa" else "فارسی", self.change_language),
        ]:
            box.add_widget(button(title, lambda f=fn: (pop.dismiss(), f())))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def new_menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        pop = self.dialog(tr("گفتگوی جدید"), box)
        box.add_widget(
            button(tr("مخاطب جدید"), lambda: (pop.dismiss(), self.contact_dialog()))
        )
        box.add_widget(
            button(tr("گروه جدید"), lambda: (pop.dismiss(), self.group_dialog()))
        )
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def profile_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        username, name = field(tr("نام کاربری")), field(tr("نام نمایشی"))
        username.text = self.engine.identity["username"]
        name.text = self.engine.identity["name"]
        box.add_widget(username)
        box.add_widget(name)
        pop = self.dialog(tr("حساب کاربری"), box)

        def save():
            self.engine.update_profile(username.text, name.text)
            pop.dismiss()
            self.refresh()

        box.add_widget(button(tr("ذخیره"), lambda: self.guarded(save)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def password_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        old, new, again = (
            field(tr("رمز فعلی"), password=True),
            field(tr("رمز جدید"), password=True),
            field(tr("تکرار رمز جدید"), password=True),
        )
        for w in (old, new, again):
            box.add_widget(w)
        pop = self.dialog(tr("تغییر رمز"), box)

        def change():
            from .crypto import derive
            import hmac

            if not hmac.compare_digest(
                derive(old.text, self.engine.vault.salt), self.engine.vault.key
            ):
                raise ValueError(tr("رمز فعلی درست نیست"))
            if new.text != again.text:
                raise ValueError(tr("تکرار رمز مطابقت ندارد"))
            with self.engine.lock:
                self.engine.vault.change_password(new.text)
            old.text = new.text = again.text = ""
            pop.dismiss()
            self.error(tr("رمز تغییر کرد؛ یک پشتیبان تازه ذخیره کنید"))

        box.add_widget(button(tr("ذخیره"), lambda: self.guarded(change)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

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
        pop = self.dialog(tr("اطلاعات گفتگو"), outer)
        box.add_widget(
            label(tr("حذف خودکار پیام‌های جدید"), size_hint_y=None, height=dp(40))
        )
        chat = self.chat
        current_ttl = self.engine.d.get("chat_ttl", {}).get(
            chat, self.engine.d.get("ttl", 86400)
        )
        for title, seconds in [
            (tr("۱ ساعت"), 3600),
            (tr("۱ روز"), 86400),
            (tr("۷ روز"), 604800),
            (tr("۳۰ روز"), 2592000),
        ]:

            def ttl(value=seconds):
                with self.engine.transaction():
                    self.engine.d.setdefault("chat_ttl", {})[chat] = value
                pop.dismiss()

            box.add_widget(button(title + (" ✓" if current_ttl == seconds else ""), ttl))
        if chat in self.engine.d["groups"]:
            group = self.engine.d["groups"][chat]["body"]
            box.add_widget(wrapped_label(tr("ارسال گروهی فقط پس از تأیید مستقل همه اعضا مجاز است")))
            box.add_widget(label(tr("کد امنیت گروه"), size_hint_y=None, height=dp(32)))
            code = self.engine.groups.safety_code(self.engine.d["groups"][chat])
            box.add_widget(wrapped_label(" ".join(code[i:i+4] for i in range(0, len(code), 4))))
            box.add_widget(wrapped_label(tr("این کد را با اعضا از مسیر مطمئن مقایسه کنید؛ با تغییر عضویت تغییر می‌کند")))
            for peer in group["members"]:
                verified = peer == self.engine.me or peer in self.engine.d["contacts"]
                box.add_widget(
                    label(
                        self.engine.peer_card(peer)["body"]["name"] + "  ·  " + tr("تأییدشده" if verified else "نیازمند تأیید"),
                        size_hint_y=None,
                        height=dp(25),
                    )
                )
                box.add_widget(wrapped_label(" ".join(peer[i:i+8] for i in range(0, len(peer), 8))))
            if group["owner"] == self.engine.me:
                box.add_widget(
                    button(
                        tr("ویرایش گروه"), lambda: (pop.dismiss(), self.group_dialog(chat))
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
                        tr("تازه‌سازی نشست"),
                        lambda: self.guarded(
                            lambda: (self.engine.reset_session(peer), pop.dismiss())
                        ),
                    )
                )
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def settings(self):
        if self.dedicated:
            from . import __version__
            box = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(14))
            box.add_widget(label(__version__))
            box.add_widget(label('TLS + Noise_NK'))
            box.add_widget(label(tr('TLS فعال است')))
            pop = self.dialog(tr('اطلاعات اتصال'), box)
            box.add_widget(button(tr('بستن'), pop.dismiss))
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
                height=dp(167),
                padding=dp(8),
                spacing=dp(5),
            )
            top = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(5))
            host, port, pin = (
                field(tr("IP یا دامنه")),
                field(tr("پورت")),
                field(tr("کلید عمومی سرور")),
            )
            host.text = value["host"]
            host.relay_transport = value.get('transport', 'noise')
            host.relay_tls_pin = value.get('tls_pin', '')
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

            panel.add_widget(button(tr("حذف"), remove))
            rows.add_widget(panel)

        for value in self.engine.d["relays"] or [None]:
            add_server(value)
        box.add_widget(button(tr("افزودن سرور"), add_server))
        pop = self.dialog(tr("سرورها"), box)

        def save():
            self.engine.configure_relays(
                [
                    {"host": h.text.strip(), "port": int(p.text), "pin": k.text.strip(), 'transport':h.relay_transport, 'tls_pin':h.relay_tls_pin}
                    for h, p, k, _ in fields
                ]
            )
            pop.dismiss()

        box.add_widget(button(tr("ذخیره"), lambda: self.guarded(save)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def privacy_dialog(self):
        engine = self.engine
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        box.add_widget(wrapped_label(tr("پراکسی باید روی همین دستگاه اجرا شود. در صورت خرابی پراکسی، اتصال مستقیم انجام نمی‌شود.")))
        row = BoxLayout(size_hint_y=None, height=dp(48))
        row.add_widget(label(tr("پراکسی اجباری")))
        enabled = CheckBox(size_hint_x=0.2, active=engine.d.get("proxy") is not None)
        row.add_widget(enabled)
        box.add_widget(row)
        port = field(tr("پورت پراکسی محلی"))
        port.text = str((engine.d.get("proxy") or {}).get("port", 9050))
        box.add_widget(port)
        box.add_widget(wrapped_label(tr("پراکسی یا Tor به‌تنهایی ناشناس‌بودن کامل را تضمین نمی‌کند. رله هنوز شناسه‌ها، زمان و اندازه پیام را می‌بیند.")))
        box.add_widget(label(tr("قفل خودکار"), size_hint_y=None, height=dp(30)))
        selected = [engine.d.get("auto_lock", 60)]
        choices = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(5))
        buttons = {}

        def select(value):
            selected[0] = value
            for seconds, widget in buttons.items():
                widget.background_color = BLUE if seconds == value else PANEL

        for seconds, title in ((30, "۳۰ ثانیه"), (60, "۱ دقیقه"), (300, "۵ دقیقه")):
            widget = button(tr(title), lambda value=seconds: select(value))
            buttons[seconds] = widget
            choices.add_widget(widget)
        select(selected[0])
        box.add_widget(choices)
        pop = self.dialog(tr("امنیت و حریم خصوصی"), box)

        def save():
            if self.engine is not engine:
                raise ValueError(tr("حساب قفل شده است"))
            proxy = {"host": "127.0.0.1", "port": int(port.text)} if enabled.active else None
            engine.configure_privacy(proxy, selected[0])
            pop.dismiss()

        box.add_widget(button(tr("ذخیره"), lambda: self.guarded(save)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def my_card(self):
        card = self.engine.card
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        fingerprint = field(tr("اثر انگشت"), multiline=True)
        fingerprint.text = card["body"]["id"]
        data = field(tr("کارت هویت"), multiline=True)
        data.text = json.dumps(card, ensure_ascii=False)
        box.add_widget(label(tr("اثر انگشت را از مسیر مطمئن به مخاطب بدهید")))
        box.add_widget(fingerprint)
        box.add_widget(data)
        pop = self.dialog(tr("کارت هویت"), box)
        box.add_widget(
            button(
                tr("ذخیره کارت"),
                lambda: self.choose_document(
                    "save",
                    "identity.json",
                    lambda f: f.write(json.dumps(card, ensure_ascii=False).encode()),
                ),
            )
        )
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def contact_dialog(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        card = field(tr("کارت هویت مخاطب"), multiline=True)
        fp = field(tr("اثر انگشت تأییدشده"), multiline=True)
        username = field(tr("نام کاربری"))
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
                        self.error(tr("کاربر آنلاین پیدا نشد؛ کارت هویت را وارد کنید"))
                    return False
                return time.monotonic() < deadline

            Clock.schedule_interval(check, 0.2)

        box.add_widget(button(tr("جستجو"), lookup))
        box.add_widget(card)
        box.add_widget(fp)
        pop = self.dialog(tr("مخاطب جدید"), box)

        def load(f):
            raw = f.read(64 * 1024).decode()
            Clock.schedule_once(lambda *_: setattr(card, "text", raw))

        box.add_widget(
            button(
                tr("بازکردن کارت"),
                lambda: self.choose_document("open", "identity.json", load),
            )
        )

        def add():
            pid = self.engine.add_contact(card.text, fp.text)
            pop.dismiss()
            self.select(self.engine.dm_id(pid))

        box.add_widget(button(tr("افزودن"), lambda: self.guarded(add)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def group_dialog(self, edit_chat=None):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        name = field(tr("نام گروه"))
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
        pop = self.dialog(tr("ویرایش گروه") if edit_chat else tr("گروه جدید"), box)

        def create():
            members = [p for p, c in chosen.items() if c.active]
            if edit_chat:
                self.engine.update_group(edit_chat, name.text, members)
                cid = edit_chat
            else:
                cid = self.engine.create_group(name.text, members)
            pop.dismiss()
            self.select(cid)

        box.add_widget(button(tr("ساخت گروه"), lambda: self.guarded(create)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def message_menu(self, mid):
        chat = self.chat
        message = next(m for m in self.engine.d["messages"][chat] if m["id"] == mid)
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
        pop = self.dialog(tr("پیام"), box)

        def delete():
            self.engine.delete(chat, mid)
            pop.dismiss()
            self.refresh()

        if chat not in self.engine.d["groups"] or message["author"] == self.engine.me:
            box.add_widget(button(tr("حذف برای همه"), lambda: self.guarded(delete)))
        if message["kind"] == "file":
            engine = self.engine

            def save_file(stream):
                if self.engine is not engine:
                    raise ValueError(tr("حساب قفل شده است"))
                # Recheck at the time the picker returns, not when the menu opened.
                with engine.lock:
                    stream.write(engine.read_file(chat, mid))

            box.add_widget(
                button(
                    tr("ذخیره فایل"),
                    lambda: self.choose_document(
                        "save",
                        Path(message["filename"]).name,
                        save_file,
                    ),
                )
            )
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def attach(self):
        if not self.chat:
            return
        if not self.engine.files_enabled:
            self.error(tr("ارسال فایل غیرفعال است"))
            return
        chat = self.chat
        engine = self.engine

        def load(f):
            if self.engine is not engine:
                raise ValueError(tr("حساب قفل شده است"))
            raw = f.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError(tr("حداکثر حجم فایل ۴ مگابایت است"))
            engine.send(
                chat,
                file_bytes=raw,
                filename=getattr(f, "display_name", None) or "file.bin",
            )

        self.choose_document("open", "file", load)

    def backup_dialog(self, on_saved=None):
        engine = self.engine

        def save(f):
            if self.engine is not engine:
                raise ValueError(tr("حساب قفل شده است"))
            with engine.lock:
                f.write(engine.vault.backup_bytes())
                f.flush()
                with engine.transaction():
                    engine.d["backup_last_at"] = int(time.time())
            if on_saved:
                on_saved()

        self.choose_document("save", "mehr-backup.mcv", save)

    def restore_dialog(self):
        if not self.screen_protected:
            self.error(tr("حفاظت صفحه فعال نشد؛ حساب باز نمی‌شود"))
            return
        if self.vault_path.exists():
            self.error(tr("حساب موجود است؛ بازیابی روی حساب موجود انجام نمی‌شود"))
            return

        def load(f):
            raw = f.read(MAX_BACKUP_BYTES + 1)
            if len(raw) > MAX_BACKUP_BYTES:
                raise ValueError(tr("حداکثر حجم پشتیبان ۱ گیگابایت است"))
            box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(10))
            pw = field(tr("رمز پشتیبان"), password=True)
            box.add_widget(pw)
            pop = self.dialog(tr("بازیابی پشتیبان"), box)

            def restore():
                vault = Vault.restore_bytes(raw, self.vault_path, pw.text)
                pw.text = ""
                pop.dismiss()
                self.enter(vault)

            box.add_widget(button(tr("بازیابی"), lambda: self.guarded(restore)))

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
        path = field(tr("مسیر کامل فایل"))
        path.text = str(Path.home() / name) if mode == "save" else ""
        box.add_widget(path)
        pop = self.dialog(tr("ذخیره فایل") if mode == "save" else tr("بازکردن فایل"), box)

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

        box.add_widget(button(tr("تأیید"), lambda: self.guarded(execute)))
        box.add_widget(button(tr("بستن"), pop.dismiss))

    def activity(self):
        self.last_activity = time.monotonic()

    def lock_account(self):
        if not self.engine:
            return
        engine = self.engine
        if not self._locking:
            self.remember_draft()
            self._locking = True
            # Hide and scrub sensitive widgets before waiting for network shutdown.
            self.scrub_widgets(self.rootbox)
            for popup in list(self.open_popups):
                popup.dismiss()
            self._view_signature = self._sidebar_signature = None
            self.rootbox.clear_widgets()
            self.rootbox.add_widget(label(tr("در حال بستن اتصال")))
        engine.stop()
        if hasattr(engine, "thread"):
            engine.thread.join(timeout=5)
        if hasattr(engine, "thread") and engine.thread.is_alive():
            Clock.schedule_once(lambda *_: self.lock_account(), 0.2)
            return
        for popup in list(self.open_popups):
            popup.dismiss()
        with engine.lock:
            engine.vault.close()
        self.engine = None
        self._locking = False
        self.chat = None
        self.compose.text = ""
        self.unlock_screen()

    def tick(self):
        if self.engine:
            if time.monotonic() - self.last_activity > self.engine.d.get("auto_lock", 60):
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
