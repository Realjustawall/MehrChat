"""Local-only camera QR scanning; camera stops when the sheet closes."""
import threading
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.graphics.texture import Texture


def open_scanner(app, callback):
    from .ui import button, wrapped_label
    box = BoxLayout(orientation='vertical',spacing=dp(12))
    box.add_widget(wrapped_label('QR مخاطب را داخل دوربین بگیرید. تصویر فقط در همین دستگاه پردازش می‌شود.', size_hint_y=None,height=dp(68),font_size=dp(14)))
    preview = Image(size_hint_y=None,height=min(dp(300), app.root.height*.4))
    box.add_widget(preview)
    popup = app.dialog('اسکن QR',box)
    app._scanner_popup = popup
    stopped = threading.Event()
    app._scanning_qr = True
    resources = {'camera':None,'poll':None,'busy':False}
    def stop(*_):
        stopped.set()
        app._scanner_popup = None
        app._scanning_qr = False
        if resources['poll']:
            resources['poll'].cancel()
        if platform == 'android' and resources['camera']:
            camera = resources['camera']
            camera.play = False
            provider = getattr(camera, '_camera', None)
            if provider and hasattr(provider, '_release_camera'):
                provider._release_camera()
            resources['camera'] = None
    popup.bind(on_dismiss=stop)
    box.add_widget(button('بستن',popup.dismiss))
    def found(value):
        if stopped.is_set():
            return
        popup.dismiss()
        callback(value)
    def unavailable(*_):
        if not stopped.is_set():
            popup.dismiss()
            app.error('دوربین در دسترس نیست یا اجازه آن داده نشده؛ از تصویر QR یا شناسه استفاده کنید.')
    if platform == 'android':
        from android.permissions import request_permissions, Permission, check_permission
        def start(*_):
            if stopped.is_set():
                return
            if not check_permission(Permission.CAMERA):
                unavailable();return
            try:
                from kivy.uix.camera import Camera
                camera=Camera(play=True,resolution=(640,480),size_hint_y=None,height=preview.height)
                box.remove_widget(preview);box.add_widget(camera,index=1)
                resources['camera']=camera
                def poll(*_):
                    if stopped.is_set() or resources['busy'] or not camera.texture:
                        return
                    texture=camera.texture
                    width,height=map(int,texture.size)
                    provider=getattr(camera,'_camera',None)
                    luminance=None
                    if provider and hasattr(provider,'_buflock'):
                        with provider._buflock:
                            if provider._buffer is not None:
                                luminance=bytes(value & 255 for value in provider._buffer)
                    raw=bytes(texture.pixels) if luminance is None else b''
                    resources['busy']=True
                    def decode():
                        try:
                            from .contact_invite import decode_android_pixels, decode_android_luminance
                            if luminance is not None:
                                value=decode_android_luminance(width,height,luminance)
                                Clock.schedule_once(lambda *_:found(value))
                                return
                            pixels=[(raw[i]<<16)|(raw[i+1]<<8)|raw[i+2] for i in range(0,len(raw),4)]
                            value=decode_android_pixels(width,height,pixels)
                            Clock.schedule_once(lambda *_:found(value))
                        except Exception:
                            pass  # No code in this frame; continue while sheet is open.
                        finally:
                            resources['busy']=False
                    threading.Thread(target=decode,daemon=True).start()
                resources['poll']=Clock.schedule_interval(poll,.7)
            except Exception:
                unavailable()
        if check_permission(Permission.CAMERA):
            start()
        else:
            request_permissions([Permission.CAMERA],lambda *_:Clock.schedule_once(start))
    else:
        def work():
            import cv2
            import zxingcpp
            camera=None
            try:
                camera=cv2.VideoCapture(0)
                if not camera.isOpened():
                    Clock.schedule_once(unavailable);return
                camera.set(cv2.CAP_PROP_FRAME_WIDTH,640)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
                while not stopped.wait(.15):
                    ok,frame=camera.read()
                    if not ok:
                        continue
                    rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                    height,width=rgb.shape[:2]
                    data=rgb.tobytes()
                    def display(*_,data=data,size=(width,height)):
                        if stopped.is_set():return
                        texture=Texture.create(size=size,colorfmt='rgb')
                        texture.blit_buffer(data,colorfmt='rgb',bufferfmt='ubyte');texture.flip_vertical()
                        preview.texture=texture
                    Clock.schedule_once(display)
                    result=zxingcpp.read_barcode(rgb,formats=zxingcpp.BarcodeFormat.QRCode)
                    if result:
                        Clock.schedule_once(lambda *_,value=result.text:found(value));return
            except Exception:
                Clock.schedule_once(unavailable)
            finally:
                if camera is not None:camera.release()
        threading.Thread(target=work,daemon=True).start()
