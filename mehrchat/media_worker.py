"""Disposable decoder process. No vault imports, no server imports, no Kivy."""
import base64
import ctypes
import io
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import warnings
import zlib

LIMIT=4*1024*1024

def linux_limits():
    import resource
    for name,amount in [('RLIMIT_CPU',8),('RLIMIT_AS',512*1024*1024),('RLIMIT_FSIZE',0),('RLIMIT_CORE',0),('RLIMIT_NOFILE',32)]:
        resource.setrlimit(getattr(resource,name),(amount,amount))

def linux_restrict():
    linux_limits()
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0):raise OSError('NoNewPrivileges unavailable')
    lib=ctypes.CDLL('libseccomp.so.2',use_errno=True)
    lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint];lib.seccomp_rule_add.restype=ctypes.c_int
    lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_release.argtypes=[ctypes.c_void_p]
    ctx=lib.seccomp_init(0x7fff0000)
    if not ctx:raise OSError('seccomp unavailable')
    deny='open openat openat2 creat socket socketpair connect bind listen accept accept4 sendto sendmsg recvfrom recvmsg execve execveat fork vfork clone clone3 ptrace process_vm_readv process_vm_writev mount umount2 bpf keyctl io_uring_setup memfd_create unlink unlinkat rename renameat renameat2 link linkat symlink symlinkat mkdir mkdirat chmod fchmod fchmodat chown fchown lchown truncate ftruncate'.split()
    try:
        for name in deny:
            number=lib.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and lib.seccomp_rule_add(ctx,0x00050000|1,number,0):raise OSError('seccomp rule failed')
        if lib.seccomp_load(ctx):raise OSError('seccomp load failed')
    finally:lib.seccomp_release(ctx)

def encode_rgb(kind,image,duration=0):
    image.thumbnail((256,256))
    rgb=image.convert('RGB');w,h=rgb.size
    return dict(v=1,kind=kind,width=w,height=h,rgb=base64.b64encode(rgb.tobytes()).decode(),duration=duration)

def decode_image(raw):
    from PIL import Image,ImageOps
    Image.MAX_IMAGE_PIXELS=12_000_000
    Image.init()  # Load plugins before the Linux filesystem/network lock.
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    if sys.platform.startswith('linux'):linux_restrict()
    with Image.open(io.BytesIO(raw),formats=['JPEG','PNG','GIF','WEBP']) as image:
        if image.width*image.height>12_000_000 or max(image.size)>16384:raise ValueError('Image dimensions exceed limits')
        image.seek(0);image.load()
        return encode_rgb('image',ImageOps.exif_transpose(image))

def decode_av(raw,kind):
    # Only a sandbox-private seekable input is exposed to the codec. Always
    # remove it, including missing-sandbox, decoder-error and timeout paths.
    with tempfile.TemporaryDirectory(prefix='mehr-preview-') as directory:
        input_path=os.path.join(directory,'input.media')
        with open(input_path,'wb') as stream:stream.write(raw)
        return _decode_av(kind,input_path)


def _decode_av(kind,input_path):
    import imageio_ffmpeg
    executable=imageio_ffmpeg.get_ffmpeg_exe()
    command=[executable,'-hide_banner','-loglevel','error','-nostdin','-threads','1',
             '-protocol_whitelist','file,pipe','-i',input_path]
    if kind=='video':
        command+=['-an','-frames:v','1','-vf','scale=256:256:force_original_aspect_ratio=decrease,pad=256:256:(ow-iw)/2:(oh-ih)/2',
                  '-pix_fmt','rgb24','-f','rawvideo','pipe:1']
        maximum=256*256*3
    else:
        command+=['-vn','-t','30','-ac','1','-ar','8000','-f','s16le','pipe:1'];maximum=30*8000*2
    if sys.platform.startswith('linux'):
        linux_limits()
        # bubblewrap hides the host filesystem and network for the codec itself.
        import shutil
        sandbox=shutil.which('bwrap')
        if not sandbox:raise OSError('Media sandbox unavailable')
        command=[sandbox,'--die-with-parent','--unshare-all','--new-session','--cap-drop','ALL',
                 '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--proc','/proc','--dev','/dev','--tmpfs','/tmp',
                 '--ro-bind','/lib64','/lib64','--ro-bind',executable,'/tmp/ffmpeg','--ro-bind',input_path,'/tmp/input.media',
                 '--chdir','/tmp','/tmp/ffmpeg',*['/tmp/input.media' if x==input_path else x for x in command[1:]]]
    result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=8,check=True)
    if len(result.stdout)>maximum:raise ValueError('Decoder output exceeds limits')
    if kind=='video':
        if len(result.stdout)!=maximum:raise ValueError('Missing video frame')
        return dict(v=1,kind='video',width=256,height=256,rgb=base64.b64encode(result.stdout).decode(),duration=0)
    data=result.stdout
    count=len(data)//2
    if not count:raise ValueError('No audio samples')
    values=struct.unpack('<'+'h'*count,data)
    step=max(1,math.ceil(count/64))
    waveform=[min(255,int(max(abs(v) for v in values[i:i+step])*255/32768)) for i in range(0,count,step)]
    return dict(v=1,kind='audio',duration=count/8000,waveform=waveform)

def run():
    # On Windows the caller puts this process in a no-capability AppContainer
    # and a memory/CPU-limited job before supplying input. No insecure fallback.
    raw=sys.stdin.buffer.read(LIMIT+1)
    if not raw or len(raw)>LIMIT:return 2
    if raw.startswith(b'MEHRCHAT_SANDBOX_PROBE\0'):
        import socket
        request=json.loads(raw.split(b'\0',1)[1])
        if sys.platform.startswith('linux'):linux_restrict()
        denied_file=False;denied_network=False
        try:
            with open(request['canary'],'rb') as stream:stream.read(1)
        except (PermissionError,FileNotFoundError):denied_file=True
        try:
            sock=socket.socket();sock.settimeout(1);sock.connect(('127.0.0.1',request['port']));sock.close()
        except PermissionError:denied_network=True
        sys.stdout.write(json.dumps(dict(files_denied=denied_file,network_denied=denied_network)))
        return 0
    from mehrchat.media import media_kind
    kind=media_kind(raw)
    if kind=='image':value=decode_image(raw)
    elif kind in ('video','audio'):value=decode_av(raw,kind)
    else:return 2
    encoded=json.dumps(value,separators=(',',':')).encode()
    if len(encoded)>272048:return 2
    sys.stdout.buffer.write(encoded);sys.stdout.buffer.flush()
    return 0
