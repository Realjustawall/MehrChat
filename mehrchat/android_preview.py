"""Binding to the no-permission isolated Android decoder service."""
import json

_binding=None

def initialize():
    """Resolve APK classes on Kivy's application thread before worker threads.

    A newly attached JNI worker has the system class loader, which cannot find
    classes bundled in this APK. Retain the application-loaded wrappers.
    """
    global _binding
    if _binding is None:
        from jnius import autoclass
        Activity=autoclass('org.kivy.android.PythonActivity')
        Bridge=autoclass('org.mehrchat.preview.PreviewBridge')
        _binding=(Activity,Bridge)

def render(raw,kind):
    if _binding is None:raise RuntimeError('Android preview binding not initialized')
    Activity,Bridge=_binding
    return str(Bridge.render(Activity.mActivity,raw,kind))

def create_preview(raw,kind):
    value=render(raw,kind)
    return json.loads(value) if value else None
