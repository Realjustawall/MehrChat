import os

os.environ.setdefault("KIVY_NO_ARGS", "1")
from mehrchat.ui import MehrApp

if __name__ == "__main__":
    app = MehrApp()
    if os.environ.get("MEHRCHAT_SMOKE_TEST") == "1":
        from kivy.clock import Clock

        def smoke(*_):
            print("NATIVE_UI_SMOKE_OK", flush=True)
            app.stop()

        Clock.schedule_once(smoke, 1)
    app.run()
