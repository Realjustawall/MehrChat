"""Codec-free, bounded preview wire format; only raw RGB reaches the UI.
The relay never imports this module or opens an attachment as a media file.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import threading

MAX_FILE=4*1024*1024
MAX_SIDE=256
MAX_PIXELS=MAX_SIDE*MAX_SIDE
MAX_ENCODED=270000

def media_kind(raw):
    if raw.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',b'GIF87a',b'GIF89a')) or (raw[:4]==b'RIFF' and raw[8:12]==b'WEBP'):return 'image'
    if len(raw)>=12 and raw[4:8]==b'ftyp':
        return 'audio' if raw[8:12] in (b'M4A ',b'M4B ') else 'video'
    if raw[:3]==b'ID3' or raw[:4] in (b'OggS',b'fLaC') or (raw[:4]==b'RIFF' and raw[8:12]==b'WAVE') or (raw[:1]==b'\xff' and len(raw)>1 and raw[1]&0xe0==0xe0):return 'audio'
    return None

def validate_preview(value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)-{'v','kind','width','height','rgb','duration','waveform'}:raise ValueError('Invalid media preview')
    if value.get('v')!=1 or value.get('kind') not in ('image','video','audio'):raise ValueError('Invalid media preview')
    duration=value.get('duration',0)
    if type(duration) not in (int,float) or not 0<=duration<=86400:raise ValueError('Invalid media duration')
    if value['kind']=='audio':
        waveform=value.get('waveform',[])
        if not isinstance(waveform,list) or len(waveform)>64 or any(type(n) is not int or not 0<=n<=255 for n in waveform):raise ValueError('Invalid waveform')
        return {'v':1,'kind':'audio','duration':duration,'waveform':waveform}
    w,h=value.get('width'),value.get('height');encoded=value.get('rgb')
    if type(w) is not int or type(h) is not int or not 1<=w<=MAX_SIDE or not 1<=h<=MAX_SIDE:raise ValueError('Invalid media dimensions')
    if not isinstance(encoded,str) or len(encoded)>MAX_ENCODED:raise ValueError('Preview too large')
    rgb=base64.b64decode(encoded,validate=True)
    if len(rgb)!=w*h*3:raise ValueError('Invalid RGB preview')
    return {'v':1,'kind':value['kind'],'width':w,'height':h,'rgb':encoded,'duration':duration}

def preview_pixels(value):
    value=validate_preview(value)
    if not value or value['kind']=='audio':return None
    return base64.b64decode(value['rgb'],validate=True)

def rgb_preview(kind,width,height,rgb,duration=0):
    if len(rgb)!=width*height*3:raise ValueError('Invalid RGB output')
    return validate_preview({'v':1,'kind':kind,'width':width,'height':height,
                             'rgb':base64.b64encode(rgb).decode(),'duration':duration})

def make_preview(raw,strict=False):
    """Only runs for an explicitly selected local file. Failure returns no preview."""
    if not raw or len(raw)>MAX_FILE:return None
    kind=media_kind(raw)
    if not kind:return None
    if sys.platform=='android' or 'ANDROID_ARGUMENT' in os.environ:
        from .android_preview import create_preview
        return validate_preview(create_preview(raw,kind))
    try:
        return validate_preview(run_isolated_decoder(raw))
    except (OSError,ValueError,subprocess.SubprocessError):
        if strict:raise
        return None


def run_isolated_decoder(raw):
    """Shared media/QR worker boundary. Never retry in the caller process."""
    if not raw or len(raw)>MAX_FILE+32:
        raise ValueError('Decoder input limit')
    worker=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'media-bin'/('MehrMedia.exe' if os.name=='nt' else 'MehrMedia')
    if worker.is_file():command=[str(worker)]
    elif not getattr(sys,'frozen',False):command=[sys.executable,str(Path(__file__).resolve().parent.parent/'media_worker_entry.py')]
    else:
        raise OSError('Packaged media worker is missing')
    try:
        if os.name=='nt':
            if not worker.is_file():raise OSError('Packaged AppContainer worker is missing')
            from .windows_preview import run_isolated
            output=run_isolated(worker,raw,timeout=15)
        else:
            # The worker installs seccomp before invoking native codecs.
            env={k:v for k,v in os.environ.items() if k in ('SYSTEMROOT','WINDIR','LD_LIBRARY_PATH')}
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,env=env,start_new_session=True)
            def terminate():
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            timer=threading.Timer(15,terminate);timer.daemon=True;timer.start()
            def feed():
                try:process.stdin.write(raw);process.stdin.close()
                except (BrokenPipeError,OSError):pass
            writer=threading.Thread(target=feed,daemon=True);writer.start()
            try:
                output=process.stdout.read(MAX_ENCODED+2049)
                if len(output)>MAX_ENCODED+2048:raise ValueError('Preview worker output limit')
                if process.wait(timeout=15):raise ValueError('Preview worker rejected media')
            finally:
                timer.cancel();terminate();process.wait(timeout=2);process.stdout.close();writer.join(1)
        if len(output)>MAX_ENCODED+2048:raise ValueError('Decoder output limit')
        return json.loads(output)
    except (OSError,ValueError,subprocess.SubprocessError):
        raise

def attachment_digest(raw):return hashlib.sha256(raw).hexdigest()

def validate_reply(value):
    if value is None:return None
    if (not isinstance(value,dict) or set(value)!={'id','text'} or not isinstance(value['id'],str)
        or len(value['id'])!=32 or any(c not in '0123456789abcdef' for c in value['id'])
        or not isinstance(value['text'],str) or len(value['text'])>280):raise ValueError('Invalid reply')
    return {'id':value['id'],'text':value['text']}
