"""Binding to the no-permission isolated Android decoder service."""
import json

def create_preview(raw,kind):
    from jnius import autoclass
    Activity=autoclass('org.kivy.android.PythonActivity')
    Bridge=autoclass('org.mehrchat.preview.PreviewBridge')
    value=Bridge.render(Activity.mActivity,raw,kind)
    return json.loads(str(value)) if value else None
