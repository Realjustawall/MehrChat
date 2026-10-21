"""Require the packaged worker to deny a real file and a listening local socket."""
import io,json,math,os,socket,subprocess,sys,tempfile,wave,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from mehrchat.media import validate_preview,preview_pixels
root=Path(__file__).resolve().parents[1]
worker=next((root/'dist/MehrChat').rglob('MehrMedia.exe' if os.name=='nt' else 'MehrMedia'))

def run(raw):
    if os.name=='nt':
        from mehrchat.windows_preview import run_isolated
        return run_isolated(worker,raw,20)
    return subprocess.check_output([str(worker)],input=raw,timeout=15)

with tempfile.TemporaryDirectory() as directory,socket.socket() as listener:
    canary=Path(directory)/'vault-canary.txt';canary.write_text('private test data')
    listener.bind(('127.0.0.1',0));listener.listen()
    raw=b'MEHRCHAT_SANDBOX_PROBE\0'+json.dumps({'canary':str(canary),'port':listener.getsockname()[1]}).encode()
    result=json.loads(run(raw))
    assert result=={'files_denied':True,'network_denied':True},result
    image=io.BytesIO();Image.new('RGB',(500,300),'green').save(image,format='JPEG')
    preview=validate_preview(json.loads(run(image.getvalue())))
    assert preview['kind']=='image' and len(preview_pixels(preview))<=256*256*3
    # An image decompression bomb must be refused within the same sandbox.
    bomb=io.BytesIO();Image.new('1',(4000,4000)).save(bomb,format='PNG')
    try:run(bomb.getvalue())
    except (OSError,subprocess.CalledProcessError):pass
    else:raise AssertionError('Oversize image was accepted')
    # WAV is generated locally; it contains no untrusted codecs before isolation.
    pcm=io.BytesIO()
    with wave.open(pcm,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
        stream.writeframes(b''.join(struct.pack('<h',int(math.sin(i*.1)*12000)) for i in range(8000)))
    if os.name=='nt':
        audio=validate_preview(json.loads(run(pcm.getvalue())))
        assert audio['kind']=='audio' and audio['waveform']
        import imageio_ffmpeg
        clip=Path(directory)/'fixture.mp4'
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-f','lavfi',
                        '-i','color=c=red:s=64x48:r=4','-t','1','-c:v','libx264','-threads','1',str(clip)],check=True)
        video=validate_preview(json.loads(run(clip.read_bytes())))
        assert video['kind']=='video' and len(preview_pixels(video))==256*256*3
    print(json.dumps(dict(files_denied=True,network_denied=True,packaged_image_decoder=True,pixel_bomb_rejected=True)))
    print('PACKAGED_MEDIA_SANDBOX_PASS')
