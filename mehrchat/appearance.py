"""Public appearance preferences; never stores account or routing secrets."""
import json
import os
from pathlib import Path

PALETTES = {
    'light': {'bg':(.94,.96,.98,1),'panel':(1,1,1,1),'text':(.08,.12,.18,1),'muted':(.39,.44,.51,1),
              'input':(.92,.94,.97,1),'focus':(.88,.94,1,1),'blue':(.14,.53,.92,1),'outgoing':(.88,.97,.82,1),
              'wallpaper':(.85,.90,.90,1)},
    'dark': {'bg':(.055,.075,.105,1),'panel':(.10,.13,.18,1),'text':(.91,.94,.98,1),'muted':(.64,.70,.78,1),
             'input':(.15,.19,.25,1),'focus':(.16,.25,.36,1),'blue':(.24,.62,.98,1),'outgoing':(.15,.28,.38,1),
             'wallpaper':(.065,.09,.13,1)},
}

class Appearance:
    def __init__(self):
        self.language='fa'; self.theme='light'; self.text_scale=1.; self.send_enter=False; self.path=None
    @property
    def colors(self): return PALETTES[self.theme]
    def load(self,path):
        self.path=Path(path)
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('language') in ('fa','en'): self.language=data['language']
            if data.get('theme') in PALETTES: self.theme=data['theme']
            if type(data.get('text_scale')) in (int,float) and .85<=data['text_scale']<=1.2: self.text_scale=data['text_scale']
            if type(data.get('send_enter')) is bool:self.send_enter=data['send_enter']
        except (OSError,ValueError,TypeError):pass
    def save(self):
        if self.path is None:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            os.chmod(temporary,0o600)
            json.dump({k:getattr(self,k) for k in ('language','theme','text_scale','send_enter')},stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)

appearance=Appearance()
