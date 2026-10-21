"""Public, key-bound contact addresses. Never contains an account password."""
import base64
import hashlib
import io
import json
import re
import struct
import unicodedata
import zlib
from urllib.parse import parse_qs, urlencode, urlsplit

from .crypto import check_card, pack

MAX_INVITE = 8192


def address(card):
    identity = check_card(card)['id']
    digest = hashlib.sha256(b'MehrChat contact address v1\0' + bytes.fromhex(identity)).digest()
    number = str(int.from_bytes(digest[:8], 'big') % 10**12).zfill(12)
    letters = int.from_bytes(digest[8:16], 'big') % 26**5
    code = ''
    for _ in range(5):
        code = chr(65 + letters % 26) + code
        letters //= 26
    return number, code


def normalize(number, code):
    if len(str(number)) > 64 or len(str(code)) > 16:
        raise ValueError('شناسه یا رمز اشتراک معتبر نیست')
    number = ''.join(str(unicodedata.digit(c)) if c.isdigit() else c for c in str(number))
    number = re.sub(r'[\s-]', '', number)
    code = str(code).strip().upper()
    if not re.fullmatch(r'[0-9]{12}', number) or not re.fullmatch(r'[A-Z]{5}', code):
        raise ValueError('شناسه باید ۱۲ رقم و رمز اشتراک باید ۵ حرف انگلیسی باشد')
    return number, code


def check_address(card, number, code):
    import hmac
    supplied = ''.join(normalize(number, code))
    if not hmac.compare_digest(''.join(address(card)), supplied):
        raise ValueError('شناسه و رمز اشتراک با هویت مخاطب مطابقت ندارند')
    return check_card(card)


def invite(card):
    number, code = address(card)
    encoded = base64.urlsafe_b64encode(pack(card)).decode().rstrip('=')
    return 'mehrchat://contact?' + urlencode(dict(v='1', id=number, key=code, card=encoded))


def parse_invite(raw):
    if not isinstance(raw, str) or len(raw.encode()) > MAX_INVITE:
        raise ValueError('کد QR معتبر نیست')
    url = urlsplit(raw.strip())
    if (url.scheme, url.netloc, url.path) != ('mehrchat', 'contact', '') or url.fragment:
        raise ValueError('این QR متعلق به مخاطب مهر نیست')
    values = parse_qs(url.query, strict_parsing=True, max_num_fields=4)
    if set(values) != {'v', 'id', 'key', 'card'} or any(len(v) != 1 for v in values.values()) or values['v'] != ['1']:
        raise ValueError('نسخه یا محتوای QR معتبر نیست')
    number, code = normalize(values['id'][0], values['key'][0])
    encoded = values['card'][0]
    raw_card = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
    card = json.loads(raw_card)
    check_address(card, number, code)
    return card, number, code


def qr_png(payload, scale=6):
    """Lossless QR with four-module quiet zone; no Pillow dependency on phones."""
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix) * scale
    scanlines = b''.join((b'\0' + bytes(0 if v else 255 for v in row for _ in range(scale))) * scale for row in matrix)
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', size, size, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b'')


def decode_image(raw):
    if len(raw) > 12 * 1024 * 1024:
        raise ValueError('حداکثر حجم تصویر ۱۲ مگابایت است')
    from kivy.utils import platform
    if platform == 'android':
        from jnius import autoclass
        BitmapFactory = autoclass('android.graphics.BitmapFactory')
        options = autoclass('android.graphics.BitmapFactory$Options')()
        options.inJustDecodeBounds = True
        BitmapFactory.decodeByteArray(raw, 0, len(raw), options)
        if options.outWidth <= 0 or options.outHeight <= 0 or options.outWidth * options.outHeight > 24_000_000:
            raise ValueError('تصویر معتبر یا قابل پردازش نیست')
        options.inJustDecodeBounds = False
        bitmap = BitmapFactory.decodeByteArray(raw, 0, len(raw), options)
        if bitmap is None:
            raise ValueError('تصویر قابل خواندن نیست')
        try:
            width, height = bitmap.getWidth(), bitmap.getHeight()
            pixels = [0] * (width * height)
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
            # pyjnius reflects Java int[] changes back into this list.
            return decode_android_pixels(width, height, pixels)
        finally:
            bitmap.recycle()
    from PIL import Image
    import zxingcpp
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 24_000_000:
            raise ValueError('تصویر بسیار بزرگ است')
        result = zxingcpp.read_barcode(image, formats=zxingcpp.BarcodeFormat.QRCode)
    if not result:
        raise ValueError('کد QR در تصویر پیدا نشد')
    return result.text


def decode_android_pixels(width, height, pixels):
    from jnius import autoclass
    source = autoclass('com.google.zxing.RGBLuminanceSource')(width, height, pixels)
    bitmap = autoclass('com.google.zxing.BinaryBitmap')(autoclass('com.google.zxing.common.HybridBinarizer')(source))
    return str(autoclass('com.google.zxing.qrcode.QRCodeReader')().decode(bitmap).getText())


def decode_android_luminance(width, height, raw):
    from jnius import autoclass
    source = autoclass('com.google.zxing.PlanarYUVLuminanceSource')(raw,width,height,0,0,width,height,False)
    bitmap = autoclass('com.google.zxing.BinaryBitmap')(autoclass('com.google.zxing.common.HybridBinarizer')(source))
    return str(autoclass('com.google.zxing.qrcode.QRCodeReader')().decode(bitmap).getText())
