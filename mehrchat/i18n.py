"""Explicit UI translation. Never translate user messages, names or protocol fields."""
import json
import os
import tempfile
from pathlib import Path

_language = 'fa'
EN = {
' عضو': ' members', 'IP یا دامنه': 'IP or hostname', 'آفلاین': 'Offline',
'اثر انگشت': 'Fingerprint', 'اثر انگشت تأییدشده': 'Independently verified fingerprint',
'اثر انگشت را از مسیر مطمئن به مخاطب بدهید': 'Share your fingerprint through a trusted channel',
'اثر انگشت مطابقت ندارد': 'Fingerprint does not match', 'ارسال': 'Send',
'ارسال فایل غیرفعال است': 'File transfers are disabled', 'اطلاعات': 'Info',
'اطلاعات پشتیبان معتبر نیست': 'Invalid backup data', 'اطلاعات گفتگو': 'Chat information',
'افزودن': 'Add', 'افزودن سرور': 'Add relay',
'این حساب در یک پنجره دیگر باز است': 'This account is open in another window',
'این نام کاربری قبلاً ثبت شده است': 'This username is already registered',
'این کارت متعلق به خودتان است': 'This is your own identity card',
'بازکردن فایل': 'Open file', 'بازکردن کارت': 'Open card', 'بازگشت': 'Back',
'بازیابی': 'Restore', 'بازیابی پشتیبان': 'Restore backup',
'برای بازیابی حساب، پشتیبان رمزگذاری‌شده را خارج از برنامه ذخیره کنید.\nبا حذف برنامه در اندروید، کلید داخل برنامه پاک می‌شود.\nرمز پشتیبان را نگه دارید؛ بازیابی بدون آن ممکن نیست.':
'Save an encrypted backup outside the app to recover your account.\nUninstalling on Android deletes the keys stored in the app.\nKeep the backup password; recovery without it is impossible.',
'بستن': 'Close', 'بعداً': 'Later', 'به سرور رسید': 'Accepted by relay',
'تأیید': 'Confirm', 'تازه‌سازی نشست': 'Reset secure session', 'تحویل شد': 'Delivered',
'تغییر رمز': 'Change password', 'تکرار رمز جدید': 'Repeat new password',
'تکرار رمز مطابقت ندارد': 'Passwords do not match', 'جستجو': 'Search',
'حداکثر حجم فایل ۴ مگابایت است': 'Maximum file size is 4 MiB',
'حداکثر حجم پشتیبان ۱ گیگابایت است': 'Maximum backup size is 1 GiB',
'حداکثر ۵ سرور': 'At most 5 relays are supported', 'حذف': 'Remove',
'حذف برای همه': 'Delete for everyone', 'حذف خودکار پیام‌های جدید': 'Auto-delete new messages',
'حساب قفل شده است': 'Account is locked',
'حساب موجود است؛ بازیابی روی آن انجام نمی‌شود': 'An account exists; it cannot be overwritten by restore',
'حساب موجود است؛ بازیابی روی حساب موجود انجام نمی‌شود': 'An account exists; it cannot be overwritten by restore',
'حساب کاربری': 'Account', 'خطای ارسال': 'Sending failed', 'در انتظار ارسال': 'Waiting to send',
'در حال اتصال': 'Connecting', 'در حال بستن اتصال': 'Closing connection',
'در گروه فقط پیام خودتان را می‌توانید برای همه حذف کنید': 'You can only delete your own group messages for everyone',
'دریافت شد': 'Received', 'ذخیره': 'Save', 'ذخیره شد': 'Saved', 'ذخیره فایل': 'Save file',
'ذخیره پشتیبان': 'Save backup', 'ذخیره کارت': 'Save card',
'رمز باید حداقل ۱۲ نویسه باشد': 'Password must contain at least 12 characters',
'رمز تغییر کرد؛ یک پشتیبان تازه ذخیره کنید': 'Password changed; save a fresh backup',
'رمز جدید': 'New password', 'رمز عبور': 'Password',
'رمز عبور یا فایل معتبر نیست': 'Incorrect password or invalid account file',
'رمز فعلی': 'Current password', 'رمز فعلی درست نیست': 'Current password is incorrect',
'رمز پشتیبان': 'Backup password', 'زمان نامعتبر است': 'Invalid retention period',
'ساخت حساب': 'Create account', 'ساخت گروه': 'Save group', 'سرورها': 'Relays',
'صف پیام‌های در انتظار پر است': 'Pending message queue is full', 'صندوق پیام پر است': 'Inbox is full',
'عملیات انجام نشد؛ اطلاعات را بررسی کنید': 'Operation failed; check the supplied information',
'فایل حساب معتبر نیست': 'Invalid account file', 'فایل در دسترس نیست': 'File is unavailable',
'فایل پشتیبان معتبر نیست': 'Invalid backup file', 'فایل: ': 'File: ',
'فقط سازنده گروه می‌تواند اعضا را تغییر دهد': 'Only the group creator can change membership',
'قفل': 'Lock', 'قفل حساب': 'Lock account', 'متصل': 'Connected',
'مخاطب تأیید نشده است': 'Contact has not been verified', 'مخاطب جدید': 'New contact',
'مسیر کامل فایل': 'Full file path', 'مشخصات سرور معتبر نیست': 'Invalid relay settings',
'منو': 'Menu', 'مهر': 'Mehr', 'نام فایل نامعتبر است': 'Invalid file name',
'نام نمایشی': 'Display name', 'نام نمایشی نامعتبر است': 'Invalid display name',
'نام کاربری': 'Username', 'نام کاربری در سرور تکراری است': 'Username already registered on relay',
'نام کاربری: ۴ تا ۳۲ حرف انگلیسی، عدد یا زیرخط': 'Username: 4–32 Latin letters, digits or underscores; start with a letter',
'نام گروه': 'Group name', 'ورود': 'Unlock', 'ویرایش گروه': 'Edit group',
'پشتیبان حساب': 'Account backup', 'پورت': 'Port', 'پیام': 'Message',
'پیام طولانی است': 'Message is too long', 'پیام منقضی شده است': 'Message has expired',
'پیام پیدا نشد': 'Message not found', 'پیام‌های قبلی': 'Earlier messages',
'کاربر آنلاین پیدا نشد؛ کارت هویت را وارد کنید': 'No online user found; import their identity card',
'کارت هویت': 'Identity card', 'کارت هویت مخاطب': 'Contact identity card',
'کارت هویت من': 'My identity card', 'کلید عمومی سرور': 'Relay public key',
'گروه به‌روزرسانی شد': 'Group updated', 'گروه جدید': 'New group', 'گروه ساخته شد': 'Group created',
'گفتگو پیدا نشد': 'Chat not found', 'گفتگوها': 'Chats', 'گفتگوی جدید': 'New chat',
'یک گفتگو انتخاب کنید': 'Select a chat', '۱ روز': '1 day', '۱ ساعت': '1 hour',
'۳۰ روز': '30 days', '۷ روز': '7 days',
'امنیت و حریم خصوصی': 'Security and privacy', 'زبان': 'Language',
'اتصال مستقیم': 'Direct connection', 'پراکسی اجباری': 'Require local SOCKS5 proxy',
'پورت پراکسی محلی': 'Local proxy port',
'پراکسی باید روی همین دستگاه اجرا شود. در صورت خرابی پراکسی، اتصال مستقیم انجام نمی‌شود.':
'The SOCKS5 proxy must run on this device. If it fails, no direct connection is made.',
'پراکسی یا Tor به‌تنهایی ناشناس‌بودن کامل را تضمین نمی‌کند. رله هنوز شناسه‌ها، زمان و اندازه پیام را می‌بیند.':
'A proxy or Tor alone cannot guarantee anonymity. The relay still sees identifiers, timing and message sizes.',
'پراکسی محلی معتبر نیست': 'Invalid local proxy settings',
'اتصال onion به پراکسی نیاز دارد': 'An onion address requires a local proxy',
'اتصال پراکسی برقرار نشد': 'Proxy connection failed',
'قفل خودکار': 'Automatic lock', '۱ دقیقه': '1 minute', '۵ دقیقه': '5 minutes',
'۳۰ ثانیه': '30 seconds', 'حفاظت صفحه فعال نشد؛ حساب باز نمی‌شود':
'Screen protection could not be enabled; the account will remain locked',
'لطفاً پیش از تلاش دوباره کمی صبر کنید': 'Please wait before trying again',
'فایل حساب بیش از حد بزرگ است': 'Account file exceeds the supported size',
}


def set_language(value):
    global _language
    if value not in ('fa', 'en'):
        raise ValueError('Unsupported language')
    _language = value


def language():
    return _language


def tr(text):
    return EN.get(str(text), str(text)) if _language == 'en' else str(text)


def alignment():
    return 'right' if _language == 'fa' else 'left'


def load_language(path):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            value = json.loads(stream.read(128)).get('language', 'fa')
        set_language(value)
    except (OSError, ValueError, TypeError, AttributeError):
        set_language('fa')


def save_language(path, value):
    if value not in ('fa', 'en'):
        raise ValueError('Unsupported language')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.language-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'language': value}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)
    set_language(value)
