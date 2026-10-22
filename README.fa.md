<div align="center">

![MehrChat](docs/assets/banner-fa.svg)

**پیام‌رسان بومی و خودمیزبان با گفت‌وگو و گروه رمزگذاری‌شده، کلید هویت روی دستگاه، پشتیبان رمزگذاری‌شده و رابط فارسی و انگلیسی.**

<img alt="Version" src="https://img.shields.io/badge/version-v0.7.1-43a8e8?style=flat-square" />
<img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%C2%B7%20Linux%20%C2%B7%20Android-354158?style=flat-square" />
<a href="https://github.com/Realjustawall/MehrChat/actions/workflows/build.yml"><img alt="CI status" src="https://img.shields.io/github/actions/workflow/status/Realjustawall/MehrChat/build.yml?branch=main&amp;label=CI&amp;style=flat-square" /></a>

<a href="https://github.com/Realjustawall/MehrChat/releases/latest"><img src="https://img.shields.io/badge/%D8%AF%D8%B1%DB%8C%D8%A7%D9%81%D8%AA-43a8e8?style=flat-square&labelColor=161b22" alt="دریافت" /></a>
<a href="docs/gallery.fa.md"><img src="https://img.shields.io/badge/%DA%AF%D8%A7%D9%84%D8%B1%DB%8C%20%D8%AF%D9%85%D9%88-5968c3?style=flat-square&labelColor=161b22" alt="گالری دمو" /></a>
<a href="#quick-start"><img src="https://img.shields.io/badge/%D8%B1%D8%A7%D9%87%E2%80%8C%D8%A7%D9%86%D8%AF%D8%A7%D8%B2%DB%8C-354158?style=flat-square&labelColor=161b22" alt="راه‌اندازی" /></a>
<a href="https://github.com/Realjustawall/MehrChat/issues"><img src="https://img.shields.io/badge/%DA%AF%D8%B2%D8%A7%D8%B1%D8%B4%20%D9%85%D8%B4%DA%A9%D9%84-354158?style=flat-square&labelColor=161b22" alt="گزارش مشکل" /></a>

[English](README.md) · [فارسی](README.fa.md)

</div>

---

[قابلیت‌های شاخص](#features) · [پیش‌نمایش](#preview) · [راه‌اندازی](#quick-start) · [توسعه](#development) · [مستندات](#documentation) · [امنیت و حریم خصوصی](#security) · [مجوز و بازخورد](#license)

<a id="features"></a>

## قابلیت‌های شاخص

| قابلیت | کاربرد |
|---|---|
| گفت‌وگوی خصوصی | پیام و گروه با رمزگذاری سرتاسری و کلید خصوصی هویت روی دستگاه کاربر. |
| مخاطبان | کارت هویت امضاشده، تبادل QR و شناسهٔ ۱۲ رقمی همراه کد عمومی پنج‌حرفی. |
| پیوست | انتقال رمزگذاری‌شده و پیش‌نمایش محدود تصویر، ویدیو و صدا در پردازش ایزوله. |
| حفظ هویت | خزانهٔ رمزگذاری‌شده، خروجی و بازیابی رمزگذاری‌شده، قفل حساب و نگهداری هویت. |
| رابط بومی | انتخاب زبان پیش از ورود، فونت وزیرمتن، ایموجی آفلاین و تم روشن و تیره. |
| خودمیزبانی | نصب تعاملی اوبونتو، TLS با اعتبارسنجی، هویت پین‌شدهٔ Noise و ساخت اختیاری کلاینت اختصاصی. |

<a id="preview"></a>

## پیش‌نمایش

رابط بومی لینوکس با حساب موقت رمزگذاری‌شده؛ تم روشن و تیره یک گفت‌وگو را نشان می‌دهند.

![MehrChat — گفت‌وگو با تم تیره](docs/assets/screenshots/fa/conversation-dark.webp)

<details>
<summary>تصاویر بیشتر</summary>

![MehrChat — گفت‌وگو با تم روشن](docs/assets/screenshots/fa/conversation-light.webp)

</details>

[مشاهدهٔ گالری کامل](docs/gallery.fa.md)

<a id="quick-start"></a>

## راه‌اندازی

بستهٔ مناسب دستگاه را از ریلیز بگیرید و همهٔ فایل‌های اجرایی همراه را نگه دارید. رلهٔ قابل‌دسترسی را آماده کنید، پروفایل اتصال عمومی آن را از مسیر قابل‌اعتماد وارد کنید و هویت رمزگذاری‌شده بسازید یا بازیابی کنید.

نصب تعاملی رله روی اوبونتو:

```bash
git clone https://github.com/Realjustawall/MehrChat.git
cd MehrChat
git checkout v0.7.1
sudo bash deploy/install-ubuntu.sh
```

نصب‌کننده حساب مدیر، نشانی تأییدشده، TLS معتبر یا CA خصوصی، هویت پین‌شدهٔ Noise و کلاینت اختصاصی اختیاری را تنظیم می‌کند. پورت پیش‌فرض رله **8787/TCP** است. مدیریت روی **8788** فقط به loopback متصل است؛ برای مدیریت راه دور از تونل SSH استفاده کنید.

پیش از توزیع پروفایل اتصال، [راهنمای کامل استقرار و کلاینت](REFERENCE.md) را بخوانید. پیش از حذف برنامه، به‌ویژه در اندروید، پشتیبان رمزگذاری‌شدهٔ هویت را بیرون از فضای برنامه نگه دارید.

<a id="development"></a>

## توسعه

Python 3.12 و پیش‌نیازهای گرافیکی و رسانه‌ای سیستم‌عامل لازم‌اند.

```bash
python -m venv .venv
# Activate .venv for your shell before continuing.
python -m pip install -r requirements.txt
python main.py
```

دستورهای بررسی:

```bash
python -m unittest discover -s tests -v
```

<a id="documentation"></a>

## مستندات

- [مرجع کامل سرور و کلاینت](REFERENCE.md)
- [مدل تهدید و محدودیت‌ها](SECURITY.md)
- [مرجع قابلیت‌ها به فارسی](FEATURES.fa.md)
- [نصب‌کنندهٔ اوبونتو](deploy/install-ubuntu.sh)
- [منشأ وابستگی‌ها و دارایی‌ها](assets/licenses/INDEX.txt)

<a id="security"></a>

## امنیت و حریم خصوصی

رمزگذاری پیام، احراز هویت مسیر انتقال و ایزوله‌سازی فایل مرزهای جداگانه‌اند. اثرانگشت یا QR مخاطب را از مسیر قابل‌اعتماد بررسی و پشتیبان رمزگذاری‌شده را حفظ کنید. فرادادهٔ رله پنهان نمی‌شود و مسیر شبکهٔ قابل‌دسترسی همچنان لازم است. کد پنج‌حرفی، اطلاعات عمومی دعوت است و رمز عبور نیست. فایل اصلی رمزگذاری‌شده الزاماً بدون بدافزار نیست. مدل تهدید، محدودیت‌ها و ریسک‌های باقی‌مانده در [SECURITY.md](SECURITY.md) آمده است.

<a id="license"></a>

## مجوز و بازخورد

تحت مجوز [GPL-3.0](LICENSE) منتشر می‌شود.

اعلان‌های مجوز و انتساب آیکون و پس‌زمینهٔ برگرفته از Telegram Web A و گرافیک Twemoji در فایل‌های همراه حفظ شده‌اند.

[گزارش اشکال و پیشنهاد بهبود](https://github.com/Realjustawall/MehrChat/issues). نسخه، سیستم‌عامل و روش بازتولید را بنویسید و اطلاعات خصوصی یا رمزها را در گزارش قرار ندهید.

---

نگهداری توسط **[Realjustawall](https://github.com/Realjustawall)**.
