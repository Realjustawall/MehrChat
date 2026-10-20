"""Exercise the real first-run connection screen against a local TLS relay."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('KIVY_NO_ARGS','1')
os.environ.setdefault('KIVY_NO_FILELOG','1')
if sys.platform=='win32':os.environ.setdefault('KIVY_GL_BACKEND','angle_sdl2')
from mehrchat.server import Relay
from mehrchat.tls import ensure_certificate,server_context
from mehrchat.deployment import write_json


with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    ready=threading.Event();state={}
    async def serve():
        relay=Relay(root/'relay')
        tls_pin=ensure_certificate(root/'relay','localhost')
        server=await asyncio.start_server(relay.handle,'127.0.0.1',0,ssl=server_context(root/'relay/tls-cert.pem',root/'relay/tls-key.pem'))
        state.update(relay=relay,loop=asyncio.get_running_loop(),stop=asyncio.Event(),profile={'host':'127.0.0.1','port':server.sockets[0].getsockname()[1],'transport':'tls-noise','pin':relay.pin,'tls_pin':tls_pin})
        ready.set()
        await state['stop'].wait()
        server.close();await server.wait_closed();relay.db.close()
    thread=threading.Thread(target=lambda:asyncio.run(serve()),daemon=True);thread.start()
    assert ready.wait(10)
    from mehrchat.ui import MehrApp,Window,Clock,TextInput,Label
    import mehrchat.ui as ui
    from mehrchat.i18n import save_language
    dedicated='--dedicated' in sys.argv
    if dedicated:
        (root/'assets').mkdir()
        write_json(root/'assets/client-profile.json',{'v':1,'locked':True,'relay':state['profile']})
        ui.ROOT=root
    else:
        write_json(root/'client/connection.json',state['profile'])
    save_language(root/'client/language.json','en')
    app=MehrApp();app.data_path=lambda:root/'client/identity.mcv'
    Window.size=(390,760)
    started=time.monotonic()
    def check_bounds(panel):
        assert panel.x >= -1 and panel.right <= app.root.width+1, 'Pre-login panel overflow'
    def resize_connection(*_):
        Window.size=(900,760)
        Clock.schedule_once(narrow_connection,0.15)
    def narrow_connection(*_):
        check_bounds(app.connection_panel)
        Window.size=(390,760)
        Clock.schedule_once(click,0.15)
    def click(*_):
        check_bounds(app.connection_panel)
        assert not app.connection_ready and app.engine is None and not hasattr(app,'password')
        if dedicated:
            assert not any(isinstance(w,TextInput) for w in app.root.walk())
            assert not any(isinstance(w,Label) and state['profile']['host'] in w.text for w in app.root.walk())
        screenshot=os.environ.get('MEHRCHAT_CONNECTION_SCREENSHOT') or (str(Path('reports')/('connection-dedicated.png' if dedicated else 'connection-standard.png')) if Path('reports').exists() else None)
        if screenshot:app.root.export_to_png(screenshot)
        state['screenshot']=screenshot
        if not dedicated:
            app.connection_tls_pin.text='0'*64
            state['negative_test']=True
        app.connectbutton.dispatch('on_release')
        Clock.schedule_interval(finish,0.1)
    def finish(*_):
        assert time.monotonic()-started<25,'Connection screen timed out'
        if state.get('negative_test'):
            if app.connectbutton.disabled:return True
            assert not app.connection_ready and not hasattr(app,'password'),'Bad pin bypassed the connection gate'
            state['negative_test']=False
            app.connection_tls_pin.text=state['profile']['tls_pin']
            app.connectbutton.dispatch('on_release')
            return True
        if not app.connection_ready:return True
        assert hasattr(app,'password') and app.engine is None
        assert not (root/'client/identity.mcv').exists(),'Preflight created a client account'
        assert app.selected_relay['pin']==state['profile']['pin']
        if not dedicated:assert (root/'client/connection.json').exists()
        if state.get('screenshot'):
            path=Path(state['screenshot'])
            app.root.export_to_png(str(path.with_name(path.stem+'-login.png')))
        Window.size=(900,760)
        Clock.schedule_once(narrow_login,0.15)
        return False
    def narrow_login(*_):
        check_bounds(app.unlock_panel)
        Window.size=(360,640)
        Clock.schedule_once(done,0.15)
    def done(*_):
        check_bounds(app.unlock_panel)
        print('Live connection screen -> authenticated TLS + Noise -> login, no account creation; responsive panels: PASS')
        app.stop()
    Clock.schedule_once(resize_connection,0.5)
    try:app.run()
    finally:
        state['loop'].call_soon_threadsafe(state['stop'].set)
        thread.join(10)
