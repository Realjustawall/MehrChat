"""Standalone worker bootstrap, deliberately separate from accounts and GUI."""
from mehrchat.media_worker import run
if __name__=='__main__':
    try:raise SystemExit(run())
    except Exception:raise SystemExit(2)
