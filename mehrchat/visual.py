"""Telegram Web inspired native drawing, pixel-measured text and offline emoji."""
from functools import lru_cache
import json
import re
from pathlib import Path
import arabic_reshaper
from bidi.algorithm import get_display
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Rectangle, Line, Fbo, ClearColor, ClearBuffers
from kivy.metrics import dp
from kivy.uix.widget import Widget
from kivy.properties import StringProperty, NumericProperty

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
FONT = str(ASSETS / 'Vazirmatn-Regular.ttf')
ICONS = json.loads((ASSETS / 'telegram-icons.json').read_text())
EMOJI = json.loads((ASSETS / 'emoji.json').read_text())
EMOJI_RE = re.compile('(' + '|'.join(re.escape(e) for e in sorted(EMOJI, key=len, reverse=True)) + ')')


def emoji_path(value):
    return str(ASSETS / 'emoji' / ('-'.join(f'{ord(c):x}' for c in value if ord(c) != 0xfe0f) + '.png'))


def shaped(value):
    return get_display(arabic_reshaper.reshape(value))


@lru_cache(maxsize=4096)
def text_width(value, size):
    return CoreLabel(text=shaped(value), font_name=FONT, font_size=size).get_extents(shaped(value))[0]


def content_width(value, size):
    return sum(size * 1.25 if part in EMOJI else text_width(part, size) for part in EMOJI_RE.split(value) if part)


def wrap_pixels(value, width, size):
    """Wrap logical text before bidi, preserving newlines and splitting long keys."""
    result = []
    for paragraph in str(value).split('\n'):
        line = ''
        for word in re.findall(r'\S+\s*|\s+', paragraph):
            if line and content_width(line + word, size) > width:
                result.append(line.rstrip()); line = ''
            # Emoji sequences stay atomic even when a long unbroken token wraps.
            units = []
            for part in EMOJI_RE.split(word):
                units.extend([part] if part in EMOJI else list(part))
            for unit in units:
                if line and content_width(line + unit, size) > width:
                    result.append(line.rstrip()); line = ''
                line += unit
        result.append(line.rstrip())
    return result or ['']


class MessageText(Widget):
    value = StringProperty('')
    font_size = NumericProperty(dp(15))
    def __init__(self, value='', **kwargs):
        super().__init__(size_hint_y=None, **kwargs)
        self.value = value
        self._draw = Clock.create_trigger(self.redraw, -1)
        self.bind(width=self._draw, pos=self._draw, value=self._draw, font_size=self._draw)
        self._draw()

    def redraw(self, *_):
        if self.width < dp(15):
            return
        lines = wrap_pixels(self.value, self.width, self.font_size)
        line_height = self.font_size * 1.65
        self.height = max(line_height, line_height * len(lines))
        self.canvas.clear()
        # Retain textures while their canvas rectangles exist.
        self._textures = []
        self.line_widths = []
        with self.canvas:
            for row, logical in enumerate(lines):
                visual = shaped(logical)
                parts = [p for p in EMOJI_RE.split(visual) if p]
                rendered = []
                for part in parts:
                    if part in EMOJI:
                        texture = CoreImage(emoji_path(part)).texture
                        rendered.append((texture, self.font_size * 1.25, self.font_size * 1.25))
                    else:
                        text = CoreLabel(text=part, font_name=FONT, font_size=self.font_size, color=(.08,.12,.16,1))
                        text.refresh()
                        rendered.append((text.texture, text.texture.width, text.texture.height))
                    self._textures.append(rendered[-1][0])
                self.line_widths.append(sum(r[1] for r in rendered))
                rtl = bool(re.search(r'[\u0600-\u06ff]', logical))
                x = self.right - sum(r[1] for r in rendered) if rtl else self.x
                y = self.top - (row + 1) * line_height
                Color(1,1,1,1)
                for texture, width, height in rendered:
                    Rectangle(texture=texture, pos=(x, y + (line_height-height)/2), size=(width,height))
                    x += width


class ChatWallpaper(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.draw, size=self.draw)

    def draw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(.84,.89,.89,1)
            Rectangle(pos=self.pos,size=self.size)
            Color(.46,.62,.61,.12)
            for row in range(int(self.height/dp(110))+1):
                for col in range(int(self.width/dp(110))+1):
                    x=self.x+col*dp(110)+(dp(45) if row%2 else 0); y=self.y+row*dp(110)
                    Line(circle=(x+dp(25),y+dp(25),dp(12)),width=dp(1.1))
                    Line(points=(x+dp(60),y+dp(60),x+dp(78),y+dp(68),x+dp(67),y+dp(77),x+dp(60),y+dp(60)),width=dp(1.1))


def input_texture(value, size):
    parts = [p for p in EMOJI_RE.split(shaped(value)) if p]
    rendered = []
    for part in parts:
        if part in EMOJI:
            rendered.append((CoreImage(emoji_path(part)).texture, int(size*1.25), int(size*1.25)))
        else:
            text=CoreLabel(text=part,font_name=FONT,font_size=size,color=(.08,.12,.16,1));text.refresh()
            rendered.append((text.texture,text.texture.width,text.texture.height))
    width=max(1,int(sum(p[1] for p in rendered)));height=max(1,int(max(p[2] for p in rendered)))
    fbo=Fbo(size=(width,height))
    with fbo:
        ClearColor(0,0,0,0);ClearBuffers();Color(1,1,1,1)
        x=0
        for texture,w,h in rendered:
            Rectangle(texture=texture,pos=(x,(height-h)/2),size=(w,h));x+=w
    fbo.draw()
    return fbo
