"""Real TLS relay + GUI gate: reject bad pin, proceed after verification, hide custom endpoint."""
import asyncio
import json
import ssl
import sys
import tempfile
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mehrchat.connection import validate_profile
from mehrchat.crypto import create_identity, public_card
from mehrchat.deployment import local_certificate
from mehrchat.server import Relay
from mehrchat.ui import MehrApp, fa
from kivy.clock import Clock
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    ca = local_certificate(root / 'tls', ['127.0.0.1'])
    ready = threading.Event()
    state = {}
    async def serve():
        relay = Relay(root / 'server')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(root / 'tls/server.pem', root / 'tls/server-key.pem')
        server = await asyncio.start_server(relay.handle, '127.0.0.1', 0, ssl=context)
        state.update(loop=asyncio.get_running_loop(), stop=asyncio.Event(), profile=dict(host='127.0.0.1', port=server.sockets[0].getsockname()[1], pin=relay.pin, transport='tls', ca=ca.strip()))
        ready.set()
        await state['stop'].wait()
        server.close()
        await server.wait_closed()
        relay.db.close()
    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    assert ready.wait(5), 'TLS relay did not start'
    app = MehrApp()
    app.data_path = lambda: root / 'identity.mcv'
    # Avoid any build-specific endpoint: only use temporary local relay state.
    import mehrchat.ui as ui
    ui.bundled_profile = lambda: None
    deadline = time.monotonic() + 20
    checks = []
    def expired():
        assert time.monotonic() < deadline, 'Connection GUI check timed out'
    def press_connect():
        next(w for w in app.root.walk() if isinstance(w, Button) and w.text == fa('بررسی اتصال و ادامه')).dispatch('on_release')
    def begin(*_):
        app.connection_profile = dict(state['profile'], pin=public_card(create_identity('wrong', 'Wrong'))['body']['box'])
        app.connection_screen()
        press_connect()
        Clock.schedule_interval(rejected, .05)
    def rejected(*_):
        expired()
        btn = next(w for w in app.root.walk() if isinstance(w, Button) and w.text == fa('بررسی اتصال و ادامه'))
        if btn.disabled:
            return True
        assert not getattr(app, 'connection_verified', False)
        assert not hasattr(app, 'password'), 'Login appeared after failed verification'
        checks.append('bad pin blocks login')
        app.connection_profile = state['profile']
        app.connection_screen()
        press_connect()
        Clock.schedule_interval(verified, .05)
        return False
    def verified(*_):
        expired()
        if not hasattr(app, 'password'):
            return True
        assert app.connection_verified
        saved = json.loads(app.vault_path.with_suffix('.connection.json').read_text())
        assert validate_profile(saved) == state['profile']
        checks.append('verified TLS opens login and saves public profile')
        app.deployment = state['profile']
        app.connection_screen()
        assert not any(isinstance(w, TextInput) for w in app.root.walk()), 'Dedicated setup exposed endpoint inputs'
        Clock.schedule_interval(dedicated, .05)
        return False
    def dedicated(*_):
        expired()
        if not app.connection_verified:
            return True
        app.settings()
        text = ' '.join(getattr(w, 'text', '') for w in app.open_popups[-1].walk())
        assert state['profile']['host'] not in text and state['profile']['pin'] not in text
        assert 'TLS + Noise NK' in text
        checks.append('dedicated connection and settings hide endpoint')
        print(json.dumps(checks), flush=True)
        app.stop()
        return False
    Clock.schedule_once(begin, .2)
    try:
        app.run()
        assert len(checks) == 3
    finally:
        state['loop'].call_soon_threadsafe(state['stop'].set)
        thread.join(timeout=5)
