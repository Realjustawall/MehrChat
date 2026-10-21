import base64
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from mehrchat.media import validate_preview,preview_pixels,rgb_preview,media_kind,validate_reply,make_preview
from mehrchat.appearance import Appearance

class PreviewWire(unittest.TestCase):
    def test_only_bounded_rgb_enters_ui(self):
        value=rgb_preview('image',2,3,bytes(range(18)))
        self.assertEqual(preview_pixels(value),bytes(range(18)))
        for changes in [{'width':True},{'width':257},{'height':0},{'rgb':'A'*270001},{'rgb':'%%%'} ,{'rgb':base64.b64encode(b'x').decode()},{'url':'https://bad.invalid/x'},{'kind':'html'},{'duration':float('nan')}]:
            with self.assertRaises((ValueError,TypeError)):
                validate_preview(dict(value,**changes))
    def test_audio_is_numbers_not_decoder_input(self):
        value={'v':1,'kind':'audio','duration':2,'waveform':[0,128,255]}
        self.assertEqual(validate_preview(value)['waveform'],[0,128,255])
        for peaks in [[256],[True],[-1],[0]*65,'url']:
            with self.assertRaises(ValueError):validate_preview(dict(value,waveform=peaks))
    def test_no_codec_is_selected_by_extension_or_url(self):
        self.assertIsNone(media_kind(b'<svg><script>bad()</script></svg>'))
        self.assertIsNone(make_preview(b'https://example.invalid/test.mp4'))
        self.assertIsNone(make_preview(b'MZ'+b'\0'*100))
    def test_reply_bounds(self):
        self.assertEqual(validate_reply({'id':'a'*32,'text':'سلام'}),{'id':'a'*32,'text':'سلام'})
        for value in [{'id':'a'*31,'text':''},{'id':'a'*32,'text':'x'*281},{'id':'a'*32,'text':'','url':'x'}]:
            with self.assertRaises(ValueError):validate_reply(value)

@unittest.skipUnless(sys.platform.startswith('linux'),'Linux source worker')
class LinuxIsolation(unittest.TestCase):
    def test_image_decodes_in_disposable_restricted_worker(self):
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(900,600),'red').save(image,format='PNG')
        preview=make_preview(image.getvalue())
        self.assertIsNotNone(preview)
        self.assertLessEqual(preview['width'],256)
        self.assertEqual(preview_pixels(preview)[:3],b'\xff\0\0')
        self.assertIsNone(make_preview(b'\x89PNG\r\n\x1a\ninvalid data'))
    def test_os_sandbox_denies_host_files_and_network(self):
        code='''from mehrchat.media_worker import linux_restrict
import socket
linux_restrict()
for action in [lambda:open('/etc/passwd','rb'),lambda:socket.socket()]:
 try:action()
 except PermissionError:pass
 else:raise RuntimeError('Sandbox escape')
print('ISOLATED')
'''
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('ISOLATED',result.stdout)

class PublicAppearance(unittest.TestCase):
    def test_persisted_preferences_allowlist_and_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'appearance.json';state=Appearance();state.load(path)
            state.language='en';state.theme='dark';state.text_scale=.85;state.send_enter=True;state.save()
            reloaded=Appearance();reloaded.load(path)
            self.assertEqual((reloaded.language,reloaded.theme,reloaded.text_scale,reloaded.send_enter),('en','dark',.85,True))
            self.assertEqual(set(json.loads(path.read_text())),{'language','theme','text_scale','send_enter'})
            path.write_text(json.dumps({'language':'unknown','theme':'bad','text_scale':500,'send_enter':'yes'}))
            state=Appearance();state.load(path)
            self.assertEqual((state.language,state.theme,state.text_scale,state.send_enter),('fa','light',1.,False))


class EncryptedMediaRoundtrip(unittest.TestCase):
    def test_caption_reply_preview_are_e2ee_and_original_stays_opaque(self):
        from test_security import clients,pump
        from mehrchat.crypto import pack
        alice,bob,charlie=clients();alice.files_enabled=True
        chat=alice.dm_id(bob.me)
        payload=b'MZ harmless opaque executable-like attachment test'
        thumbnail=rgb_preview('image',2,2,b'\xff\x00\x00'*4)
        reply={'id':'a'*32,'text':'متن پاسخ'}
        mid=alice.send(chat,'زیرنویس',file_bytes=payload,filename='sample.bin',preview=thumbnail,reply_to=reply)
        wire=pack(alice.d['outbox'][-1]['item'])
        self.assertNotIn(payload,wire);self.assertNotIn('زیرنویس'.encode(),wire)
        pump([alice,bob,charlie])
        received=bob.d['messages'][chat][-1]
        self.assertEqual(received['preview'],thumbnail);self.assertEqual(received['reply'],reply)
        self.assertEqual(bob.read_file(chat,mid),payload)
        received['file_sha256']='0'*64
        with self.assertRaises(ValueError):bob.read_file(chat,mid)
