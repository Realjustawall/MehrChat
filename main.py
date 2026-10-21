import os
import tempfile
import sys
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")
if sys.platform == "win32":
    os.environ.setdefault("KIVY_GL_BACKEND", "angle_sdl2")


def run():
    from mehrchat.ui import MehrApp

    app = MehrApp()
    mode = os.environ.get("MEHRCHAT_SMOKE_TEST")
    if mode == "flow":
        from mehrchat.smoke import install

        with tempfile.TemporaryDirectory() as directory:
            app.data_path = lambda: Path(directory) / "identity.mcv"
            install(app, os.environ["MEHRCHAT_SMOKE_RESULT"])
            try:app.run()
            finally:app.on_stop()
    else:
        if mode == "1":
            from kivy.clock import Clock

            def done(*_):
                print("NATIVE_UI_SMOKE_OK", flush=True)
                app.stop()

            Clock.schedule_once(done, 1)
        app.run()


if __name__ == "__main__":
    if os.environ.get("MEHRCHAT_SMOKE_TEST") == "flow" and os.environ.get(
        "MEHRCHAT_SMOKE_LOG"
    ):
        import traceback

        previous_streams = sys.stdout, sys.stderr
        with open(
            os.environ["MEHRCHAT_SMOKE_LOG"], "w", encoding="utf-8", buffering=1
        ) as log:
            sys.stdout = sys.stderr = log
            try:
                run()
            except BaseException:
                traceback.print_exc(file=log)
                log.flush()
                os._exit(1)
            finally:
                sys.stdout, sys.stderr = previous_streams
    else:
        run()
