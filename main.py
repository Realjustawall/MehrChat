import os
import tempfile
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
from mehrchat.ui import MehrApp

if __name__ == "__main__":
    app = MehrApp()
    mode = os.environ.get("MEHRCHAT_SMOKE_TEST")
    if mode == "flow":
        from mehrchat.smoke import install

        with tempfile.TemporaryDirectory() as directory:
            app.data_path = lambda: Path(directory) / "identity.mcv"
            install(app, os.environ["MEHRCHAT_SMOKE_RESULT"])
            app.run()
    else:
        if mode == "1":
            from kivy.clock import Clock

            def done(*_):
                print("NATIVE_UI_SMOKE_OK", flush=True)
                app.stop()

            Clock.schedule_once(done, 1)
        app.run()
