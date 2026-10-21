"""APK classes must be resolved on the application thread, then reused."""
import concurrent.futures
import json
import sys
import threading
import types
import unittest
from unittest.mock import patch
from mehrchat import android_preview

class AndroidPreviewBinding(unittest.TestCase):
    def test_background_decode_reuses_application_loaded_classes(self):
        application_thread=threading.get_ident();activity=object()
        class Bridge:
            @staticmethod
            def render(context,raw,kind):
                self.assertIs(context,activity)
                self.assertNotEqual(threading.get_ident(),application_thread)
                self.assertEqual((raw,kind),(b'fixture','probe'))
                return json.dumps({'files_denied':True})
        def autoclass(name):
            self.assertEqual(threading.get_ident(),application_thread)
            return types.SimpleNamespace(mActivity=activity) if name.endswith('PythonActivity') else Bridge
        with patch.object(android_preview,'_binding',None),patch.dict(sys.modules,{'jnius':types.SimpleNamespace(autoclass=autoclass)}):
            android_preview.initialize()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result=pool.submit(android_preview.create_preview,b'fixture','probe').result(timeout=5)
            self.assertEqual(result,{'files_denied':True})

    def test_uninitialized_worker_fails_closed(self):
        with patch.object(android_preview,'_binding',None):
            with self.assertRaises(RuntimeError):android_preview.create_preview(b'fixture','image')
