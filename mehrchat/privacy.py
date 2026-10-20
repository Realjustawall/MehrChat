"""Endpoint privacy controls. These do not defeat a compromised operating system."""
import os


def disable_core_dumps():
    if os.name == 'posix':
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            # Linux: block same-user ptrace and process-memory reads by default.
            import ctypes
            ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE
        except (ImportError, AttributeError, OSError, ValueError):
            pass


def protect_android_screen(callback):
    """Run on Android's UI thread and acknowledge the flag before opening a vault."""
    from android.runnable import run_on_ui_thread
    from jnius import autoclass

    @run_on_ui_thread
    def apply():
        try:
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            window = activity.getWindow()
            flag = autoclass('android.view.WindowManager$LayoutParams').FLAG_SECURE
            window.addFlags(flag)
            if autoclass('android.os.Build$VERSION').SDK_INT >= 31:
                window.setHideOverlayWindows(True)
            callback(bool(window.getAttributes().flags & flag))
        except Exception:
            callback(False)
    apply()


def protect_windows_screen():
    if os.name != 'nt':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetActiveWindow.restype = wintypes.HWND
        user.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
        user.SetWindowDisplayAffinity.restype = wintypes.BOOL
        handle = user.GetActiveWindow()
        return bool(handle and user.SetWindowDisplayAffinity(handle, 0x11))
    except (AttributeError, OSError):
        return False
