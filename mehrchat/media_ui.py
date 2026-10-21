"""Safe previews: validate bounded raw RGB/waveform; never decode original media."""
from kivy.graphics import Color,Rectangle,Line
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.uix.image import Image
from kivy.uix.widget import Widget
from kivy.uix.behaviors import ButtonBehavior
from .appearance import appearance
from .media import validate_preview,preview_pixels

class PreviewImage(ButtonBehavior,Image):
    def __init__(self,preview,**kwargs):
        preview=validate_preview(preview)
        texture=Texture.create(size=(preview['width'],preview['height']),colorfmt='rgb')
        texture.blit_buffer(preview_pixels(preview),colorfmt='rgb',bufferfmt='ubyte')
        texture.flip_vertical()
        super().__init__(texture=texture,size_hint_y=None,fit_mode='contain',**kwargs)
        self.height=dp(180)
        self.bind(width=self.fit)
    def fit(self,*_):
        self.height=min(dp(220),max(dp(80),self.width*self.texture.height/max(1,self.texture.width)))

class AudioWaveform(ButtonBehavior,Widget):
    def __init__(self,preview,**kwargs):
        self.preview=validate_preview(preview)
        super().__init__(size_hint_y=None,height=dp(64),**kwargs)
        self.bind(pos=self.draw,size=self.draw)
    def draw(self,*_):
        self.canvas.clear();values=self.preview.get('waveform',[]) or [2]*48
        with self.canvas:
            Color(*appearance.colors['blue'])
            step=max(1,self.width/max(1,len(values)))
            for i,amplitude in enumerate(values):
                height=max(dp(2),(self.height-dp(12))*amplitude/255)
                Rectangle(pos=(self.x+i*step,self.center_y-height/2),size=(max(1,step-dp(2)),height))

def preview_widget(preview):
    preview=validate_preview(preview)
    return AudioWaveform(preview) if preview['kind']=='audio' else PreviewImage(preview)
