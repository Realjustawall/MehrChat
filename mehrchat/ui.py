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
from kivy.uix.image import Image
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.core.clipboard import Clipboard
from kivy.core.image import Image as CoreImage
import io
from .visual import ICONS, EMOJI, emoji_path, wrap_pixels, content_width, MessageText, ChatWallpaper, EMOJI_RE, input_texture, EMOJI_DATA, emoji_texture
from .contact_invite import address, invite, parse_invite, check_address, qr_png, decode_image
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label as KivyLabel
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.spinner import Spinner as KivySpinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.utils import platform
from .vault import Vault, MAX_BACKUP_BYTES
from .client import Engine, safe_filename
from .crypto import public_card, check_card
from .connection import bundled_profile, validate_profile, probe
from .media import make_preview, validate_preview
from .media_ui import preview_widget
from .appearance import appearance
from .i18n import tr
from .visual import shaped
from . import __version__

ROOT = Path(__file__).resolve().parent.parent
FONT = str(ROOT / "assets" / "Vazirmatn-Regular.ttf")
BG = (0.93, 0.95, 0.96, 1)
PANEL = (1, 1, 1, 1)
BLUE = (0.20, 0.565, 0.925, 1)
TEXT = (0.08, 0.12, 0.16, 1)
MUTED = (0.44, 0.47, 0.50, 1)


def fa(s):
    # Compatibility name: widgets keep logical Unicode for editing/testing.
    # Bidi and joining happen once, after wrapping, at texture generation.
    return tr(s)


def apply_palette():
    global BG, PANEL, BLUE, TEXT, MUTED
    c=appearance.colors
    BG,PANEL,BLUE,TEXT,MUTED=(c[k] for k in ('bg','panel','blue','text','muted'))


def render_label(widget):
    if widget.font_name.endswith('TelegramIcons.ttf'):
        return
    width=widget.text_size[0]
    lines=wrap_pixels(widget.text,max(1,width-dp(2)),widget.font_size) if width else widget.text.split('\n')
    widget._label.text='\n'.join(shaped(line) for line in lines)
    if getattr(widget,'auto_height',False):widget._label.text_size=(width,None)


class Label(KivyLabel):
    def texture_update(self,*args):
        render_label(self)
        result=super().texture_update(*args)
        if getattr(self,'auto_height',False):self.height=max(dp(24),self.texture_size[1]+dp(4))
        return result


class ChoiceOption(SpinnerOption):
    def __init__(self,**kw):
        super().__init__(**kw)
        self.font_name=FONT;self.font_size=sp(14*appearance.text_scale)
        self.color=TEXT;self.background_normal='';self.background_color=PANEL
    def texture_update(self,*args):
        self._label.text=shaped(tr(self.text))
        return super().texture_update(*args)


class Spinner(KivySpinner):
    def __init__(self,**kw):
        kw.setdefault('font_name',FONT);kw.setdefault('font_size',sp(14*appearance.text_scale))
        kw.setdefault('color',TEXT);kw.setdefault('background_normal','')
        kw.setdefault('background_color',appearance.colors['input'])
        kw.setdefault('option_cls',ChoiceOption)
        super().__init__(**kw)
    def texture_update(self,*args):
        self._label.text=shaped(tr(self.text))
        return super().texture_update(*args)


class Surface(BoxLayout):
    def __init__(self, color=None, **kw):
        color = PANEL if color is None else color
        super().__init__(**kw)
        with self.canvas.before:
            self.fill = Color(*color)
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
    def texture_update(self,*args):
        render_label(self)
        return super().texture_update(*args)

    def __init__(self, **kw):
        color = kw.pop("background_color", BLUE)
        super().__init__(background_color=(0, 0, 0, 0), background_normal="", background_down="", **kw)
        with self.canvas.before:
            self.fill = Color(*color)
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            Color(1, 1, 1, 1)
        self.bind(pos=self.redraw, size=self.redraw, state=self.redraw, disabled=self.redraw)
        self.base_color = color
        self.halign = "center"
        self.valign = "middle"
        self.bind(size=lambda w,v:setattr(w,"text_size",(max(1,v[0]-dp(16)),max(1,v[1]-dp(4)))))

    def redraw(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size
        factor = 0.75 if self.state == "down" or self.disabled else 1
        self.fill.rgba = tuple(c * factor for c in self.base_color[:3]) + (self.base_color[3],)



def icon_button(name, callback, primary=False):
    widget = ModernButton(text=ICONS.get(name, ICONS.get('more', '')), font_name=str(ROOT/'assets/TelegramIcons.ttf'),
                          font_size=sp(25 * appearance.text_scale), color=(1,1,1,1) if primary else MUTED,
                          background_color=BLUE if primary else (0,0,0,0),
                          size_hint=(None,None),size=(dp(44),dp(44)),pos_hint={'center_y':.5})
    widget.shape.radius=[dp(22)]
    widget.bind(on_release=lambda *_:callback())
    return widget


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
        initial=label(name.strip()[:1], font_size=sp(23 * appearance.text_scale))
        initial.color=(1,1,1,1)
        self.add_widget(initial)


def label(text="", **kw):
    kw.setdefault("font_size", sp(14 * appearance.text_scale))
    kw.setdefault("halign", "center")
    kw.setdefault('valign', 'middle')
    widget = Label(text=fa(text), font_name=FONT, color=TEXT, **kw)
    widget.bind(size=lambda w, size: setattr(w, 'text_size', size))
    widget.text_size = widget.size
    return widget


def wrapped_label(text, **kw):
    widget=label(text, halign='right' if appearance.language=='fa' else 'left', valign='middle', **kw)
    widget.auto_height=True;widget.size_hint_y=None
    return widget


def button(text, callback, **kw):
    color = kw.pop("background_color", BLUE)
    b = ModernButton(
        text=fa(text),
        font_name=FONT,
        font_size=sp(14 * appearance.text_scale),
        background_color=color,
        color=(1,1,1,1) if color == BLUE else TEXT,
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
            self.fill = Color(*appearance.colors["input"])
            self.shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
            self.ink = Color(*(self.foreground_color if self.text else self.hint_text_color))
        self.bind(pos=self.redraw, size=self.redraw, focus=self.redraw, text=self.redraw)

    def redraw(self, *_):
        self.shape.pos, self.shape.size = self.pos, self.size
        self.fill.rgba = appearance.colors["focus"] if self.focus else appearance.colors["input"]
        self.ink.rgba = (1,1,1,1) if not self.password and getattr(self,'color_emoji',False) and self.text else (self.foreground_color if self.text else self.hint_text_color)

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
        self._get_line_options()
        if self.password and not hint:
            return super()._create_line_label(text, hint)
        # Explicit options prevent the hint from reusing a stale/default font.
        # Password hints still need Persian joining; only password contents mask.
        if not hint and getattr(self,'color_emoji',False):
            cache=getattr(self,'_emoji_lines',{})
            key=(text,self.font_size,appearance.theme)
            if key not in cache:
                if len(cache)>48:cache.clear()
                cache[key]=input_texture(text,self.font_size)
            self._emoji_lines=cache
            return cache[key].texture
        from kivy.core.text import Label as CoreLabel
        core=CoreLabel(text=shaped(text),font_name=self.font_name,font_size=self.font_size,
                       color=(1,1,1,1),padding=(0,0))
        core.refresh()
        return core.texture

    def _get_text_width(self, text, tab_width, cached):
        self._get_line_options()
        if self.password:
            return super()._get_text_width(text,tab_width,cached)
        return content_width(text.replace('\t',' '*tab_width),self.font_size)

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if getattr(self,'is_composer',False) and keycode[1] in ('enter','numpadenter'):
            if appearance.send_enter and 'shift' not in modifiers:
                App.get_running_app().send()
                return True
        return super().keyboard_on_key_down(window,keycode,text,modifiers)

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
        hint_text=tr(hint),
        halign="right" if appearance.language=="fa" else "left",
        password=password,
        multiline=multiline,
        font_name=FONT,
        font_size=sp(14 * appearance.text_scale),
        background_color=(0.12, 0.18, 0.23, 1),
        foreground_color=TEXT,
        cursor_color=BLUE,
        padding=[dp(12), dp(8)],
        hint_text_color=MUTED,
        size_hint_y=None,
        height=dp(48) if not multiline else dp(120),
    )


class MehrApp(App):
    title = "مهر"

    def build(self):
        if platform=='android':
            from .android_preview import initialize
            initialize()
        self.vault_path = self.data_path()
        if not getattr(self,"test_mode",False):
            appearance.load(self.vault_path.with_suffix(".appearance.json"))
        apply_palette()
        Window.clearcolor = BG
        self.title = tr("مهر")
        self.engine = None
        self.chat = None
        self.reply_to = None
        self.rootbox = BoxLayout(orientation="vertical", padding=0, spacing=0)
        self.open_popups = []
        self.last_activity = time.monotonic()
        Window.bind(
            on_touch_down=lambda *_: self.activity(),
            on_key_down=lambda *_: self.activity(),
        )
        # SDL/ANGLE can dispatch on_resize before Window.size is updated.
        # Coalesce the events and choose the pane mode on the next clock tick.
        self._resize_trigger = Clock.create_trigger(self.resize_layout, 0)
        Window.bind(on_resize=self._resize_trigger, size=self._resize_trigger)
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
        if self.engine and hasattr(self, 'messagebox'):
            self._view_signature = None
            Clock.schedule_once(lambda *_: self.refresh(), .15)
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
        # Compact, scrollable sheets: the keyboard/small screen never clips fields.
        def compact(widget):
            if isinstance(widget, Label) and widget.size_hint_y is not None:
                widget.size_hint_y = None
                widget.height = dp(56)
            elif isinstance(widget, ScrollView):
                widget.size_hint_y = None
                widget.height = min(dp(250), Window.height * .34)
                return
            for child in widget.children:
                compact(child)
        compact(body)
        body.size_hint_y = None
        if hasattr(body, 'minimum_height'):
            body.bind(minimum_height=body.setter('height'))
            body.height = body.minimum_height
        outer = Surface(orientation='vertical', padding=dp(20), spacing=dp(12))
        header = BoxLayout(size_hint_y=None, height=dp(44))
        header.add_widget(label(title, halign='right', font_size=sp(20 * appearance.text_scale)))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        scroll.add_widget(body)
        outer.add_widget(header)
        outer.add_widget(scroll)
        popup = Popup(title='', title_size=0, separator_height=0,
                      background='', background_color=(0,0,0,0),
                      overlay_color=(.03,.07,.12,.45), content=outer, size_hint=(None,None))
        header.add_widget(icon_button('close', popup.dismiss))
        def fit(*_):
            popup.width = min(dp(500), Window.width-dp(28))
            popup.height = min(Window.height-dp(36), max(dp(240), body.height+dp(140)))
        body.bind(height=fit)
        Window.bind(size=fit)
        self.open_popups.append(popup)
        def dismiss(*_):
            Window.unbind(size=fit)
            if popup in self.open_popups:
                self.open_popups.remove(popup)
        popup.bind(on_dismiss=dismiss)
        Clock.schedule_once(fit)
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
        panel.add_widget(label("مهر", font_size=sp(28 * appearance.text_scale), size_hint_y=None, height=dp(64)))
        panel.add_widget(label(title, font_size=sp(20 * appearance.text_scale), size_hint_y=None, height=dp(36)))
        note = wrapped_label(subtitle, font_size=sp(13 * appearance.text_scale), size_hint_y=None, height=dp(60))
        note.color = MUTED
        panel.add_widget(note)
        selectors=BoxLayout(size_hint_y=None,height=dp(40),spacing=dp(8))
        language=Spinner(text='فارسی' if appearance.language=='fa' else 'English',values=('فارسی','English'))
        theme=Spinner(text='روشن' if appearance.theme=='light' else 'تیره',values=('روشن','تیره'))
        selectors.add_widget(language);selectors.add_widget(theme);panel.add_widget(selectors)
        language.bind(text=lambda w,v:self.set_appearance(language='fa' if v=='فارسی' else 'en'))
        theme.bind(text=lambda w,v:self.set_appearance(theme='light' if v=='روشن' else 'dark'))
        self.language_choice,self.theme_choice=language,theme
        Clock.schedule_once(fit)
        return panel

    def set_appearance(self,language=None,theme=None,text_scale=None,send_enter=None):
        draft = self.compose.text if self.engine and hasattr(self,'compose') else None
        chat = self.chat if self.engine else None
        # Preserve incomplete onboarding input when toggling language or theme.
        connection_fields={k:w.text for k,w in getattr(self,'_connection_form',{}).items()}
        fields={k:getattr(self,k).text for k in ('username','displayname','password') if hasattr(self,k)}
        for k,v,allowed in [('language',language,('fa','en')),('theme',theme,('light','dark'))]:
            if v is not None and v in allowed:setattr(appearance,k,v)
        if text_scale is not None:appearance.text_scale=max(.85,min(1.2,float(text_scale)))
        if send_enter is not None:appearance.send_enter=bool(send_enter)
        if not getattr(self,'test_mode',False):appearance.save()
        apply_palette();Window.clearcolor=BG;self.title=tr('مهر')
        for popup in list(self.open_popups):popup.dismiss()
        if self.engine:
            self.shell()
            if chat:self.select(chat)
            self.compose.text=draft or ''
        elif getattr(self,'connection_verified',False) or getattr(self,'test_mode',False):
            self.unlock_screen()
            for k,v in fields.items():getattr(self,k).text=v
        else:
            self.connection_screen()
            for k,v in connection_fields.items():
                if k in self._connection_form:self._connection_form[k].text=v

    def appearance_dialog(self):
        box=BoxLayout(orientation='vertical',spacing=dp(8))
        pop=self.dialog('نمایش و زبان',box)
        for title,action in [('فارسی',lambda:self.set_appearance(language='fa')),
                             ('English',lambda:self.set_appearance(language='en')),
                             ('روشن',lambda:self.set_appearance(theme='light')),
                             ('تیره',lambda:self.set_appearance(theme='dark'))]:
            box.add_widget(button(title,action,background_color=BG))
        box.add_widget(label('اندازه متن',size_hint_y=None,height=dp(28)))
        row=BoxLayout(size_hint_y=None,height=dp(44),spacing=dp(6))
        for title,value in [('کوچک',.85),('معمولی',1.),('بزرگ',1.15)]:
            row.add_widget(button(title,lambda n=value:self.set_appearance(text_scale=n),background_color=BG))
        box.add_widget(row)
        toggle=CheckBox(active=appearance.send_enter,size_hint_y=None,height=dp(40))
        box.add_widget(label('ارسال با Enter',size_hint_y=None,height=dp(28)))
        box.add_widget(toggle)
        box.add_widget(label('Shift+Enter برای خط جدید',size_hint_y=None,height=dp(30)))
        box.add_widget(button('ذخیره',lambda:self.set_appearance(send_enter=toggle.active)))
        box.add_widget(button('بستن',pop.dismiss,background_color=BG))

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
        self._connection_form=inputs
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
                                size_hint_y=None, height=dp(48), background_normal="", background_color=BG, color=TEXT)
            panel.add_widget(transport)
            ca = field("گواهی CA اختصاصی (PEM)، برای گواهی عمومی خالی", multiline=True)
            ca.text = current.get("ca", "")
            self._connection_form.update(transport=transport,ca=ca)
            # Paste a public profile exported by the Ubuntu installer.
            imported = field("پروفایل اتصال JSON", multiline=True)
            self._connection_form["imported"]=imported
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
        status = wrapped_label("آماده بررسی اتصال", size_hint_y=None, height=dp(48), font_size=sp(13 * appearance.text_scale))
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
            width=dp(360),
            padding=dp(10),
            spacing=dp(4),
        )
        toolbar = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(8))
        toolbar.add_widget(icon_button('hamburger', self.main_menu))
        toolbar.add_widget(label('مهر', font_size=sp(24 * appearance.text_scale), halign='right'))
        toolbar.add_widget(icon_button('new-chat-filled', self.new_menu))
        self.sidebar.add_widget(toolbar)
        self.search = field("جستجو")
        self.search.bind(text=lambda *_: self.refresh())
        self.sidebar.add_widget(self.search)
        caption = label("گفتگوهای شما", font_size=sp(12 * appearance.text_scale), size_hint_y=None, height=dp(30))
        caption.color = BLUE
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
            header.add_widget(icon_button('arrow-left', self.show_chat_list))
        self.header_avatar = Avatar('مهر', '10', pos_hint={'center_y': .5})
        header.add_widget(self.header_avatar)
        titles = BoxLayout(orientation="vertical")
        self.heading = label("مهر", halign="right", shorten=True, font_size=sp(17 * appearance.text_scale))
        self.statuslabel = label("آفلاین", font_size=sp(12 * appearance.text_scale), halign="right")
        self.statuslabel.color = MUTED
        titles.add_widget(self.heading)
        titles.add_widget(self.statuslabel)
        header.add_widget(titles)
        header.add_widget(icon_button('more', self.chat_info))
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
        wallpaper = FloatLayout()
        wallpaper.add_widget(ChatWallpaper(pos_hint={"x":0,"y":0}))
        self.messagescroll.pos_hint = {"x":0,"y":0}
        wallpaper.add_widget(self.messagescroll)
        self.mainpane.add_widget(wallpaper)
        composer = Surface(
            size_hint_y=None, height=dp(68), padding=dp(10), spacing=dp(7)
        )
        composer.add_widget(icon_button('attach', self.attach))
        composer.add_widget(icon_button('smile', self.emoji_picker))
        self.compose = field("پیام", multiline=True)
        self.compose.color_emoji = True
        self.compose.is_composer = True
        self.compose.height = dp(48)
        def fit_composer(*_):
            self.compose.height = max(dp(48),min(dp(144),self.compose.minimum_height))
            composer.height = self.compose.height + dp(20)
        self.compose.bind(minimum_height=fit_composer)
        Clock.schedule_once(fit_composer)
        self.compose.bind(
            text=lambda w, t: setattr(
                w, "halign", "right" if re.search(r"[\u0600-\u06ff]", t) else "left"
            )
        )
        composer.add_widget(self.compose)
        composer.add_widget(icon_button("send", self.send, primary=True))
        self.composer = composer
        self.reply_bar=Surface(size_hint_y=None,height=0,padding=[dp(10),0],color=BG)
        self.mainpane.add_widget(self.reply_bar)
        self.mainpane.add_widget(composer)
        def pane_resized(*_):
            self._view_signature = None
            Clock.schedule_once(lambda *_: self.refresh(), .05)
        self.mainpane.bind(width=pane_resized)
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
                    str(len(self.engine.d["groups"][cid]["body"]["members"])) + tr(" عضو")
                )
            row = ChatRow(
                size_hint_y=None,
                height=dp(76),
                padding=dp(10),
                spacing=dp(10),
                color=BLUE if cid == self.chat else PANEL,
            )
            row.bind(on_release=lambda _, c=cid: self.select(c))
            row.add_widget(Avatar(name, cid, pos_hint={"center_y": 0.5}))
            column = BoxLayout(orientation="vertical", spacing=dp(3))
            title = label(name, halign="right", shorten=True, shorten_from="right")
            subtitle = label(
                preview.replace("\n", " "),
                halign="right",
                font_size=sp(12 * appearance.text_scale),
                shorten=True,
                shorten_from="right",
            )
            title.color = (1,1,1,1) if cid == self.chat else TEXT
            subtitle.color = (.87,.94,1,1) if cid == self.chat else MUTED
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
                    font_size=sp(10 * appearance.text_scale),
                )
                stamp.color = (.87,.94,1,1) if cid == self.chat else MUTED
                row.add_widget(stamp)
            self.chatlist.add_widget(row)
        if not self.chatlist.children:
            empty = wrapped_label("هنوز گفتگویی ندارید\nبا + یک مخاطب یا گروه اضافه کنید", size_hint_y=None, height=dp(140), font_size=sp(14 * appearance.text_scale))
            empty.color = MUTED
            self.chatlist.add_widget(empty)

    def select(self, cid):
        if cid != self.chat:self.cancel_reply()
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
            available = max(dp(150), self.mainpane.width - dp(40))
            previous_day = None
            for m in messages[-self.view_limit :]:
                day = time.strftime("%Y/%m/%d", time.localtime(m["created"]))
                if day != previous_day:
                    date_row = AnchorLayout(size_hint_y=None, height=dp(36))
                    chip = Surface(size_hint=(None, None), size=(dp(120), dp(28)), color=appearance.colors["input"] if appearance.theme=="dark" else (.68,.77,.76,.9))
                    chip.add_widget(label(day, font_size=sp(11 * appearance.text_scale)))
                    date_row.add_widget(chip)
                    self.messagebox.add_widget(date_row)
                    previous_day = day
                own = m["author"] == self.engine.me
                text = (
                    m.get("text", "")
                    if m["kind"] != "file"
                    else tr("فایل: ") + m.get("filename", "") + ("\n"+m.get("text", "") if m.get("text") else "")
                )
                # Width follows the actual content area; height follows texture metrics.
                width = min(available * .82, dp(440), max(dp(140), max(content_width(v,dp(15)) for v in text.split("\n"))+dp(28)))
                line = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(5))
                if own:
                    line.add_widget(Label())
                bubble = Surface(orientation='vertical', padding=[dp(12),dp(6)],
                                 size_hint=(None,None), width=width,
                                 color=appearance.colors["outgoing"] if own else PANEL)
                bubble.rect.radius = [dp(16),dp(16),dp(4),dp(16)] if own else [dp(16),dp(16),dp(16),dp(4)]
                bubble.bind(minimum_height=bubble.setter('height'))
                bubble.bind(height=lambda w,h,row=line: setattr(row,'height',h))
                if self.chat in self.engine.d["groups"]:
                    bubble.add_widget(
                        label(
                            self.engine.peer_card(m["author"])["body"]["name"],
                            font_size=sp(11 * appearance.text_scale),
                            size_hint_y=None,
                            height=dp(17),
                        )
                    )
                    line.height += dp(17)
                if m.get('reply'):
                    text='> '+m['reply']['text']+'\n'+text
                display = MessageText(text)
                bubble.add_widget(display)
                if m['kind']=='file' and m.get('preview'):
                    try:
                        media=preview_widget(m['preview'])
                        media.bind(on_release=lambda _,message=m:self.media_preview(message))
                        bubble.add_widget(media)
                        if m['preview']['kind'] in ('video','audio'):
                            duration=m['preview'].get('duration',0)
                            caption=tr('ویدیو' if m['preview']['kind']=='video' else 'صدا')
                            bubble.add_widget(label(caption+(' · %.1fs'%duration if duration else ''),size_hint_y=None,height=dp(22),font_size=sp(12*appearance.text_scale)))
                    except ValueError:pass
                footer = BoxLayout(size_hint_y=None, height=dp(23))
                stamp = time.strftime("%H:%M", time.localtime(m["created"]))
                footer.add_widget(label(stamp, font_size=sp(10 * appearance.text_scale), halign='right'))
                if own:
                    checks = label('', size_hint_x=None, width=dp(23), font_size=sp(16 * appearance.text_scale))
                    checks.font_name = str(ROOT / 'assets/TelegramIcons.ttf')
                    state_icon = 'message-read' if m['state'] == 'تحویل شد' else ('check' if m['state'] == 'به سرور رسید' else ('clock' if m['state'] == 'در انتظار ارسال' else 'warning'))
                    checks.text = ICONS[state_icon]
                    checks.color = (.25,.57,.32,1)
                    footer.add_widget(checks)
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
                self.engine.send(self.chat, self.compose.text, reply_to=self.reply_to)
                self.engine.d.setdefault("drafts", {}).pop(self.chat, None)
            self.compose.text = ""
            self.cancel_reply()
            self.refresh()

        self.guarded(action)

    def main_menu(self):
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        pop = self.dialog("منو", box)
        for title, fn in [
            ("نمایش و زبان", self.appearance_dialog),
            ("حساب کاربری", self.profile_dialog),
            ("سرورها", self.settings),
            ("QR و شناسه من", self.my_card),
            ("تغییر رمز", self.password_dialog),
            ("ذخیره پشتیبان", self.backup_dialog),
            ("درباره مهر و مجوزها", self.about_dialog),
            ("قفل", self.lock_account),
        ]:
            box.add_widget(button(title, lambda f=fn: (pop.dismiss(), f())))
        box.add_widget(button("بستن", pop.dismiss))

    def about_dialog(self):
        box=BoxLayout(orientation='vertical',spacing=dp(12))
        box.add_widget(wrapped_label('MehrChat '+__version__+'\nرابط بومی با آیکون‌های Telegram Web A\nCopyright Telegram Web A contributors\nGPL-3.0 · نرم‌افزار آزاد، بدون ضمانت\nTwemoji graphics © Twitter / contributors · CC-BY-4.0\nhttps://github.com/Realjustawall/MehrChat\nhttps://github.com/Ajaxy/telegram-tt\nمجوزها همراه برنامه در assets/licenses هستند.',size_hint_y=None,height=dp(260),font_size=sp(14 * appearance.text_scale)))
        pop=self.dialog('درباره مهر',box)
        box.add_widget(button('بستن',pop.dismiss,background_color=BG))

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
            transport = Spinner(text=value.get("transport", "noise"), values=("tls", "noise"), size_hint_y=None, height=dp(44), font_name=FONT, background_normal="", background_color=BG, color=TEXT)
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
        number, secret = address(card)
        payload = invite(card)
        box = BoxLayout(orientation='vertical', spacing=dp(12), padding=dp(4))
        image_data = qr_png(payload)
        texture = CoreImage(io.BytesIO(image_data), ext='png').texture
        texture.mag_filter = 'nearest'
        qr = Image(texture=texture, size_hint_y=None, height=dp(238))
        box.add_widget(qr)
        box.add_widget(label(self.engine.identity['name'], font_size=sp(22 * appearance.text_scale), size_hint_y=None, height=dp(36)))
        box.add_widget(label(' '.join(number[i:i+4] for i in range(0,12,4)), font_size=sp(27 * appearance.text_scale), size_hint_y=None, height=dp(42)))
        box.add_widget(label(secret, font_size=sp(23 * appearance.text_scale), size_hint_y=None, height=dp(36)))
        box.add_widget(wrapped_label('مخاطب QR را اسکن کند یا شناسه و کد ۵ حرفی را وارد کند. این رمز، رمز ورود حساب شما نیست.', font_size=sp(13 * appearance.text_scale), size_hint_y=None, height=dp(70)))
        pop = self.dialog('QR و شناسه من', box)
        box.add_widget(button('کپی شناسه و کد', lambda: Clipboard.copy(number + ' ' + secret)))
        box.add_widget(button('کپی لینک مخاطب', lambda: Clipboard.copy(payload), background_color=BG))
        box.add_widget(button('ذخیره تصویر QR', lambda: self.choose_document('save','mehr-contact.png',lambda f:f.write(image_data)), background_color=BG))
        box.add_widget(button('ذخیره کارت', lambda: self.choose_document('save','identity.json',lambda f:f.write(json.dumps(card,ensure_ascii=False).encode())), background_color=BG))
        box.add_widget(button('بستن', pop.dismiss, background_color=BG))

    def contact_dialog(self):
        box = BoxLayout(orientation='vertical', spacing=dp(12), padding=dp(4))
        box.add_widget(wrapped_label('با شناسه و کد عمومی یا QR مخاطب را بیابید. این کد رمز حساب نیست؛ هویت را از مسیر مطمئن تأیید کنید.', size_hint_y=None, height=dp(84), font_size=sp(14 * appearance.text_scale)))
        number, secret = field('شناسه ۱۲ رقمی'), field('کد عمومی تطبیق ۵ حرفی')
        number.input_filter = lambda value, undo: ''.join(c for c in value if c.isdecimal() or c in ' -')
        number.halign = secret.halign = 'center'
        number.font_size = dp(23)
        secret.font_size = dp(21)
        secret.bind(text=lambda w,t:setattr(w,'text',t.upper()) if t != t.upper() else None)
        box.add_widget(number); box.add_widget(secret)
        preview = wrapped_label('پس از بررسی، نام مخاطب اینجا نمایش داده می‌شود.', size_hint_y=None, height=dp(62), font_size=sp(14 * appearance.text_scale))
        raw_card, fingerprint = field('کارت هویت مخاطب', multiline=True), field('اثر انگشت تأییدشده', multiline=True)
        engine = self.engine
        pop = self.dialog('افزودن مخاطب', box)
        self._contact_form = {'number':number, 'secret':secret, 'card':raw_card, 'fingerprint':fingerprint, 'popup':pop}
        def fill(card):
            if self.engine is not engine or pop not in self.open_popups:
                return
            check_address(card, number.text, secret.text)
            raw_card.text = json.dumps(card, ensure_ascii=False)
            fingerprint.text = card['body']['id']
            preview.text = fa(card['body']['name'] + '\n@' + card['body']['username'])
            add_button.disabled = False
        def scanned(payload):
            card, n, code = parse_invite(payload)
            number.text, secret.text = n, code
            fill(card)
        self._contact_fill_invite = scanned
        def invalidate(*_):
            raw_card.text = fingerprint.text = ''
            add_button.disabled = True
            preview.text = fa('برای نمایش مخاطب، بررسی را بزنید یا QR را اسکن کنید.')
        def paste():
            value = Clipboard.paste().strip()
            if value.startswith('mehrchat:'):
                scanned(value)
            else:
                match = re.fullmatch(r'([\d\s-]{12,20})\s+([a-zA-Z]{5})', value)
                if not match:
                    raise ValueError('لینک مخاطب یا شناسه و کد عمومی تطبیق را کپی کنید')
                number.text, secret.text = match.groups()
        def lookup():
            key = engine.lookup_contact(number.text, secret.text)
            preview.text = fa('در حال بررسی هویت مخاطب…')
            deadline = time.monotonic()+15
            def check(*_):
                if self.engine is not engine or pop not in self.open_popups:
                    return False
                with engine.lock:
                    result = engine.d['lookup_results'].pop(key, None)
                if result is not None:
                    if result.get('card'):
                        self.guarded(lambda:fill(result['card']))
                    else:
                        preview.text = fa('مخاطب پیدا نشد؛ شناسه، کد و سرور مشترک را بررسی کنید.')
                    return False
                if time.monotonic() >= deadline:
                    preview.text = fa('پاسخی دریافت نشد. اتصال را بررسی کنید یا QR مخاطب را اسکن کنید.')
                    return False
                return True
            event = Clock.schedule_interval(check,.2)
            pop.bind(on_dismiss=lambda *_:event.cancel())
        box.add_widget(button('بررسی مخاطب', lambda:self.guarded(lookup)))
        actions = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        actions.add_widget(button('اسکن QR', lambda:self.scan_qr(lambda value:self.guarded(lambda:scanned(value))), background_color=BG))
        def load_image(stream):
            raw=stream.read(4*1024*1024+1)
            def work():
                try:
                    value=decode_image(raw)
                    Clock.schedule_once(lambda *_:self.guarded(lambda:scanned(value)))
                except Exception:
                    Clock.schedule_once(lambda *_:self.error('QR معتبر در تصویر پیدا نشد'))
            threading.Thread(target=work,daemon=True).start()
        actions.add_widget(button('تصویر QR', lambda:self.choose_document('open','mehr-contact.png',load_image), background_color=BG))
        box.add_widget(actions)
        box.add_widget(button('چسباندن لینک یا شناسه', lambda:self.guarded(paste), background_color=BG))
        box.add_widget(preview)
        def add():
            card=json.loads(raw_card.text)
            check_address(card,number.text,secret.text)
            pid=engine.add_contact(raw_card.text,card['body']['id'])
            pop.dismiss();self.select(engine.dm_id(pid))
        add_button=button('افزودن',lambda:self.guarded(add))
        add_button.disabled=True
        number.bind(text=invalidate);secret.bind(text=invalidate)
        box.add_widget(add_button)
        # Advanced signed-card import is retained for existing contacts/backups.
        def advanced():
            fields=BoxLayout(orientation='vertical',spacing=dp(10))
            fields.add_widget(raw_card);fields.add_widget(fingerprint)
            extra=self.dialog('کارت هویت و اثر انگشت',fields)
            def validate():
                card=json.loads(raw_card.text)
                if fingerprint.text.replace(' ','').lower()!=check_card(card)['id']:
                    raise ValueError('اثر انگشت مطابقت ندارد')
                n,code=address(card)
                number.text,secret.text=n,code
                fill(card);extra.dismiss()
            fields.add_widget(button('تأیید کارت',lambda:self.guarded(validate)))
            fields.add_widget(button('بازکردن کارت',lambda:self.choose_document('open','identity.json',lambda f:setattr(raw_card,'text',f.read(64*1024).decode())),background_color=BG))
        box.add_widget(button('ورود کارت هویت',advanced,background_color=BG))
        box.add_widget(button('بستن',pop.dismiss,background_color=BG))

    def scan_qr(self, callback):
        from .qr_scanner import open_scanner
        open_scanner(self,callback)

    def emoji_picker(self):
        box=BoxLayout(orientation='vertical',spacing=dp(8))
        popup=self.dialog('ایموجی',box)
        search=field('جستجوی ایموجی (انگلیسی)');box.add_widget(search)
        groups={'همه':None,'اخیر':'recent','چهره‌ها':'Smileys & Emotion','افراد':'People & Body',
                'حیوانات و طبیعت':'Animals & Nature','غذا':'Food & Drink','سفر':'Travel & Places',
                'فعالیت‌ها':'Activities','اشیا':'Objects','نمادها':'Symbols','پرچم‌ها':'Flags'}
        category=Spinner(text='همه',values=tuple(groups),size_hint_y=None,height=dp(40))
        box.add_widget(category)
        tones=Spinner(text='همه رنگ‌های پوست',values=('همه رنگ‌های پوست','پیش‌فرض','پوست روشن','پوست گندمی روشن','پوست گندمی','پوست گندمی تیره','پوست تیره'),
                      size_hint_y=None,height=dp(40));box.add_widget(tones)
        scroller=ScrollView(do_scroll_x=False,size_hint_y=None,height=min(dp(270),Window.height*.32))
        grid=GridLayout(cols=6,spacing=dp(5),size_hint_y=None)
        grid.bind(minimum_height=grid.setter('height'));scroller.add_widget(grid);box.add_widget(scroller)
        nav=BoxLayout(size_hint_y=None,height=dp(40),spacing=dp(6));box.add_widget(nav)
        page_label=label('');state={'page':0}
        canonical=[e for e in EMOJI if not EMOJI_DATA[e].get('alias')]
        def fill(reset=False):
            if reset:state['page']=0
            term=search.text.strip().casefold();group=groups[category.text]
            recent=self.engine.d.get('recent_emoji',[]) if self.engine else []
            values=recent if group=='recent' else canonical
            values=[e for e in values if e in EMOJI_DATA and (group in (None,'recent') or EMOJI_DATA[e]['category']==group)
                    and (not term or term in EMOJI_DATA[e]['name'].casefold() or term in e)]
            skin=tones.values.index(tones.text)
            if skin:
                values=[e for e in values if (not any(chr(c) in e for c in range(0x1f3fb,0x1f400))) if skin==1] if skin==1 else [e for e in values if chr(0x1f3fb+skin-2) in e]
            pages=max(1,(len(values)+47)//48);state['page']=max(0,min(state['page'],pages-1))
            page_label.text=f"{state['page']+1} / {pages} · {len(values)}"
            grid.clear_widgets();grid.cols=max(4,min(8,int(max(dp(180),popup.width-dp(50))/dp(42))))
            for value in values[state['page']*48:(state['page']+1)*48]:
                tile=ChatRow(size_hint_y=None,height=dp(38),padding=dp(5),color=BG)
                tile.add_widget(Image(texture=emoji_texture(value)))
                def insert(*_,emoji=value):
                    self.compose.insert_text(emoji)
                    if self.engine:
                        with self.engine.transaction():
                            recent=self.engine.d.get('recent_emoji',[])
                            self.engine.d['recent_emoji']=([emoji]+[e for e in recent if e!=emoji])[:32]
                tile.bind(on_release=insert);grid.add_widget(tile)
            scroller.scroll_y=1
        def move(n):state['page']+=n;fill()
        nav.add_widget(button('صفحه قبل',lambda:move(-1),background_color=BG));nav.add_widget(page_label)
        nav.add_widget(button('صفحه بعد',lambda:move(1),background_color=BG))
        search.bind(text=lambda *_:fill(True));category.bind(text=lambda *_:fill(True));tones.bind(text=lambda *_:fill(True))
        popup.bind(width=lambda *_:fill())
        box.add_widget(button('بستن',popup.dismiss,background_color=BG))
        Clock.schedule_once(lambda *_:fill())

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
        box.add_widget(wrapped_label(message["state"], size_hint_y=None, height=dp(40), font_size=sp(13 * appearance.text_scale)))
        pop = self.dialog("پیام", box)

        def delete():
            self.engine.delete(chat, mid)
            pop.dismiss()
            self.refresh()

        box.add_widget(button('پاسخ',lambda:self.set_reply(message,pop)))
        if message.get('text'):
            box.add_widget(button('کپی متن',lambda:Clipboard.copy(message['text']),background_color=BG))
        if message.get('preview'):
            box.add_widget(button('پیش‌نمایش',lambda:self.media_preview(message),background_color=BG))
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

    def cancel_reply(self):
        self.reply_to=None
        if hasattr(self,'reply_bar'):
            self.reply_bar.clear_widgets();self.reply_bar.height=0

    def set_reply(self,message,popup=None):
        self.reply_to={'id':message['id'],'text':(message.get('text') or message.get('filename',''))[:280]}
        self.reply_bar.clear_widgets();self.reply_bar.height=dp(42)
        self.reply_bar.add_widget(label(self.reply_to['text'],shorten=True,font_size=sp(12*appearance.text_scale)))
        self.reply_bar.add_widget(icon_button('close',self.cancel_reply))
        if popup:popup.dismiss()
        self.compose.focus=True

    def media_preview(self,message):
        if not message.get('preview'):return
        box=BoxLayout(orientation='vertical',spacing=dp(8))
        box.add_widget(label(message.get('filename',''),size_hint_y=None,height=dp(36),font_size=sp(13*appearance.text_scale)))
        box.add_widget(preview_widget(message['preview']))
        box.add_widget(wrapped_label('فایل اصلی فقط با انتخاب شما ذخیره می‌شود؛ بازکردن خودکار غیرفعال است.',size_hint_y=None,height=dp(60),font_size=sp(12*appearance.text_scale)))
        pop=self.dialog('پیش‌نمایش',box)
        box.add_widget(button('بستن',pop.dismiss,background_color=BG))

    def attach(self):
        if not self.chat:return
        if not self.engine.files_enabled:
            self.error('ارسال فایل غیرفعال است');return
        def load(stream):
            raw=stream.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise ValueError('حداکثر حجم فایل ۴ مگابایت است')
            filename=getattr(stream,'display_name',None) or Path(str(getattr(stream,'name','file.bin'))).name
            self.attachment_dialog(raw,safe_filename(filename))
        self.choose_document('open','file',load)

    def attachment_dialog(self,raw,filename):
        engine,chat=self.engine,self.chat
        box=BoxLayout(orientation='vertical',spacing=dp(8))
        pop=self.dialog('ارسال',box);state={'active':True,'preview':None}
        pop.bind(on_dismiss=lambda *_:state.update(active=False))
        box.add_widget(label(filename+f' · {len(raw)/1024:.1f} KiB',size_hint_y=None,height=dp(36),font_size=sp(13*appearance.text_scale)))
        stage=BoxLayout(orientation='vertical',size_hint_y=None,height=dp(100))
        status=wrapped_label('در حال آماده‌سازی پیش‌نمایش…');stage.add_widget(status);box.add_widget(stage)
        caption=field('زیرنویس فایل',multiline=True);caption.height=dp(80);caption.color_emoji=True;box.add_widget(caption)
        def send_file():
            if self.engine is not engine or self.chat!=chat:raise ValueError('حساب قفل شده است')
            engine.send(chat,caption.text,file_bytes=raw,filename=filename,preview=state['preview'],reply_to=self.reply_to)
            self.cancel_reply();pop.dismiss();self.refresh()
        send=button('ارسال',lambda:self.guarded(send_file));send.disabled=True;box.add_widget(send)
        box.add_widget(button('بستن',pop.dismiss,background_color=BG))
        def worker():
            try:preview=make_preview(raw)
            except Exception:preview=None
            def finish(*_):
                if not state['active'] or self.engine is not engine:return
                state['preview']=preview;stage.clear_widgets()
                if preview:
                    view=preview_widget(preview);stage.height=dp(190) if preview['kind']!='audio' else dp(70);stage.add_widget(view)
                else:
                    stage.height=dp(80);stage.add_widget(wrapped_label('به دلیل محدودیت ایمنی، پیش‌نمایش ساخته نشد؛ فایل را می‌توانید جداگانه ذخیره کنید.',font_size=sp(12*appearance.text_scale)))
                send.disabled=False
            Clock.schedule_once(finish)
        threading.Thread(target=worker,daemon=True).start()
        self._attachment_state=state

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
            scanner = getattr(self, "_scanner_popup", None)
            if scanner:
                scanner.dismiss()
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
