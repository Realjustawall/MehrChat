"""Exercise measured text at small-phone and desktop widths before packaging."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.label import Label
from mehrchat.ui import MehrApp, PersianInput
from mehrchat.visual import MessageText, widget_pixels
from mehrchat.vault import Vault
from mehrchat.crypto import create_identity, public_card
from mehrchat.contact_invite import invite

app=MehrApp();app.test_mode=True
temporary=tempfile.TemporaryDirectory()
app.data_path=lambda:Path(temporary.name)/'layout.mcv'
sizes=[(1100,760),(800,600),(390,844),(320,640)]
report=[]

def start(*_):
    app.enter(Vault(app.vault_path,'temporary layout password','alice','نام نمایشی طولانی برای آزمون رابط کاربری'))
    for p in list(app.open_popups):p.dismiss()
    peer=public_card(create_identity('bobby','مخاطب با نام فارسی نسبتاً طولانی'))
    app.engine.add_contact(json.dumps(peer),peer['body']['id'])
    app.select(app.engine.dm_id(peer['body']['id']))
    for text in ['سلام! 😊 چطوری؟ ❤️','متن ترکیبی English and فارسی با ایموجی 🎉 و عدد ۱۲۳۴۵۶۷۸۹۰ ' * 4,'ABC123'*80]:
        app.engine.send(app.chat,text)
    app.compose.text='سلام\n😊 ❤️\nEnglish'
    app.refresh()
    Clock.schedule_once(resize,.2)

def resize(*_):
    if not sizes:
        print(json.dumps(report,ensure_ascii=False));print('LAYOUT_BOUNDS_PASS')
        app.stop();return
    Window.size=sizes.pop(0)
    Clock.schedule_once(check,.8)

def check(*_):
    from mehrchat.ui import fa
    if app.mobile:app.select(app.chat)
    app.refresh()
    Clock.schedule_once(assert_messages,.4)

def assert_messages(*_):
    texts=[w for w in app.messagebox.walk() if isinstance(w,MessageText)]
    assert len(texts)==3
    for text in texts:
        assert text.width>0 and text.height>0
        assert all(width<=text.width+1 for width in text.line_widths),(Window.size,text.width,text.line_widths)
        assert text.x >= text.parent.x and text.right<=text.parent.right+1
        assert text.top<=text.parent.top+1 and text.y>=text.parent.y
    assert app.compose.height >= min(app.compose.minimum_height,144)
    for logical,texture in zip(app.compose._lines,app.compose._lines_labels):
        if not logical.strip():continue
        rgba=texture.pixels
        assert any(rgba[i+3]>0 and min(rgba[i:i+3])<180 for i in range(0,len(rgba),4)), 'A plain composer line became white when another line contained emoji'
    for logical,rect in zip(app.compose._lines,app.compose._lines_rects):
        if logical.strip():
            assert max(rect.tex_coords[1::2])-min(rect.tex_coords[1::2])>0, 'Composer rendered a zero-height texture region'
    composed=widget_pixels(app.compose)
    assert any(composed[i+3]>0 and max(composed[i:i+3])<180 for i in range(0,len(composed),4)), 'Composited input contains no visible text'
    app.contact_dialog()
    Clock.schedule_once(assert_dialog,.3)

def assert_dialog(*_):
    popup=app.open_popups[-1]
    assert popup.width<=Window.width and popup.height<=Window.height
    form=app._contact_form
    assert form['number'].width<=popup.width and form['secret'].width<=popup.width
    # Actual image decode/autofill is checked in the compiled flow on both OSes.
    app._contact_fill_invite(invite(app.engine.peer_card(next(iter(app.engine.d['contacts'])))))
    assert len(form['number'].text)==12 and len(form['secret'].text)==5
    report.append({'window':list(Window.size),'message_bounds':True,'dialog_bounds':True,'autofill':True})
    popup.dismiss()
    Clock.schedule_once(resize,.1)

Clock.schedule_once(start,.2)
try:
    app.run()
finally:
    app.on_stop()
