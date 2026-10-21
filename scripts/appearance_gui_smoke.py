"""Real UI regression: logical Persian, both languages/themes, narrow viewport."""
import io,json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.text import Label as CoreLabel
from kivy.metrics import dp
from mehrchat.ui import MehrApp,PersianInput,Label,FONT
from mehrchat.appearance import appearance
from mehrchat.visual import MessageText,shaped,widget_pixels,EMOJI_DATA
from mehrchat.crypto import create_identity,public_card
from mehrchat.vault import Vault
from mehrchat.media import rgb_preview

app=MehrApp();app.test_mode=True;tmp=tempfile.TemporaryDirectory()
app.data_path=lambda:Path(tmp.name)/'appearance.mcv'
cases=[('fa','light'),('fa','dark'),('en','light'),('en','dark')];results=[]

def setup(*_):
    Window.size=(390,844)
    Clock.schedule_once(onboarding,.3)

def onboarding(*_):
    for language,theme in cases:
        app.set_appearance(language=language,theme=theme)
        assert hasattr(app,'language_choice') and hasattr(app,'theme_choice')
        expected='رمز عبور' if language=='fa' else 'Password'
        assert app.password.hint_text==expected
        texture=app.password._create_line_label(app.password.hint_text,hint=True)
        expected_label=CoreLabel(text=shaped(expected),font_name=FONT,font_size=app.password.font_size);expected_label.refresh()
        assert texture.size==expected_label.texture.size
        for widget in app.root.walk():
            if isinstance(widget,PersianInput):assert widget.font_name==FONT
    app.enter(Vault(app.vault_path,'temporary appearance password','alice','آزمایش'))
    for p in list(app.open_popups):p.dismiss()
    peer=public_card(create_identity('bobby','مخاطب'))
    app.engine.add_contact(json.dumps(peer),peer['body']['id']);app.select(app.engine.dm_id(peer['body']['id']))
    app.engine.send(app.chat,'سلام 👨‍👩‍👧‍👦 👍🏽\nEnglish متن ترکیبی\n'+('ABC'*100))
    app.engine.files_enabled=True
    app.engine.send(app.chat,'زیرنویس فارسی',file_bytes=b'opaque test file',filename='test.png',preview=rgb_preview('image',8,6,bytes([220,60,30])*48))
    app.compose.text='پیش‌نویس\n👨‍👩‍👧‍👦 👍🏽\nEnglish'
    Clock.schedule_once(next_case,.3)

def next_case(*_):
    if not cases:
        print(json.dumps(results));print('BILINGUAL_THEME_MEDIA_PASS');app.stop();return
    language,theme=cases.pop(0);draft=app.compose.text
    app.set_appearance(language=language,theme=theme)
    assert app.compose.text==draft
    Clock.schedule_once(check,.5)

def check(*_):
    assert app.compose.width>dp(80) and app.compose.right<=Window.width
    for widget in app.messagebox.walk():
        if isinstance(widget,MessageText):
            assert hasattr(widget,'line_widths'),(widget.value,widget.size,app.mainpane.size,app.messagebox.size)
            assert max(widget.line_widths,default=0)<=widget.width+1
    assert appearance.colors['text'][0]>.8 if appearance.theme=='dark' else appearance.colors['text'][0]<.2
    assert widget_pixels(app.compose)
    app.contact_dialog()
    Clock.schedule_once(check_popup,.3)

def check_popup(*_):
    popup=app.open_popups[-1]
    for w in popup.content.walk():
        if isinstance(w,Label) and w.text and w.font_name==FONT:
            w.texture_update()
            assert w.texture_size[1]<=w.height+dp(4),(w.text,w.texture_size,w.size)
    popup.dismiss()
    results.append({'language':appearance.language,'theme':appearance.theme,'draft':True,'bounds':True,'safe_rgb_preview':True})
    Clock.schedule_once(next_case,.2)
Clock.schedule_once(setup,.2)
try:app.run()
finally:app.on_stop()
