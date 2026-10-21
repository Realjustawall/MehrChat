"""Standalone worker bootstrap, deliberately separate from accounts and GUI."""
from mehrchat.media_worker import run
if __name__=='__main__':
    try:raise SystemExit(run())
    except Exception as error:
        import json
        print(json.dumps({'error':type(error).__name__,'detail':str(error)[:200]}))
        raise SystemExit(2)
