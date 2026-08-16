# قاب عکس دوبعدی — Photo Frame 2D

استودیوی تحت‌وب برای تبدیل عکس به تصویر لایه‌ای (posterized) و ثبت سفارش ساخت قاب.

A Persian, right-to-left web studio that turns a photograph into a layered
poster image using an admin-defined colour palette, then lets the customer order
a physical frame at a chosen size with an estimated price.

---

## چه می‌کند؟ / What it does

بازدیدکننده بدون نیاز به ورود، عکسی را بارگذاری می‌کند، یکی از پروفایل‌های رنگی
تعریف‌شده توسط مدیر را انتخاب می‌کند، پارامترهای پردازش را تنظیم می‌کند و
نتیجه را زنده می‌بیند. سپس اندازهٔ قاب را انتخاب می‌کند، هزینهٔ تقریبی را
می‌بیند و سفارش را برای بررسی مدیران ثبت می‌کند.

1. **Render** — upload a photo, pick a colour profile, tune the pipeline, see the result. No sign-in required.
2. **Size & price** — choose a frame width; the height follows the photo's aspect ratio automatically. An approximate price is shown live.
3. **Order** — sign in (in a modal, so the render is never lost), confirm, submit.
4. **Review** — admins triage orders in the Django admin panel and set the final price.
5. **Produce** — admins export any order as a printable **3D STL plate**, one terrace per colour.

مدیران همچنین تعیین می‌کنند صفحهٔ اصلی با چه تنظیماتی باز شود: پروفایل رنگی
پیش‌فرض و همهٔ پارامترهای پردازش، بدون نیاز به تغییر کد.

---

## شروع سریع / Quick start

روی یک سرور اوبونتو، فقط همین یک دستور:

```bash
sudo ./scripts/install.sh
```

That single idempotent command installs system packages, builds the virtualenv,
applies migrations, collects static files, writes a systemd unit, opens the
firewall port and health-checks the result. Run it as often as you like.

سپس یک مدیر بسازید:

```bash
sudo ./scripts/create-admin.sh
```

- برنامه: `http://<server>:8080/`
- پنل مدیریت: `http://<server>:8080/admin/`

### اجرای محلی برای توسعه / Local development

```bash
./run.sh                       # http://0.0.0.0:8080 with autoreload
.venv/bin/python manage.py test
```

---

## اسکریپت‌های نگهداری / Maintenance scripts

همهٔ اسکریپت‌ها از هر مسیری قابل اجرا هستند و مسیر پروژه را خودشان پیدا می‌کنند.

| اسکریپت | کار |
|---|---|
| `scripts/install.sh` | نصب/به‌روزرسانی کامل + سرویس systemd. **idempotent** |
| `scripts/uninstall.sh` | حذف سرویس. داده‌ها به‌صورت پیش‌فرض حفظ می‌شوند |
| `scripts/create-admin.sh` | ساخت یا ارتقای کاربر به مدیر کل |
| `scripts/backup.sh` | بسته‌بندی کل وضعیت در یک فایل zip |
| `scripts/restore.sh` | بازگرداندن وضعیت از فایل پشتیبان |

```bash
sudo ./scripts/install.sh --port 9000        # نصب روی پورت دیگر
./scripts/backup.sh --keep 7                 # پشتیبان + نگه‌داری ۷ نسخهٔ آخر
./scripts/restore.sh --inspect backup.zip    # فقط محتوا را نشان بده
sudo ./scripts/restore.sh backup.zip         # بازیابی کامل
sudo ./scripts/uninstall.sh                  # حذف سرویس، حفظ داده‌ها
```

جزئیات کامل در [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

---

## چه چیزی «وضعیت» است؟ / What counts as state

هر چیزی که در یک clone تازه وجود ندارد و باید نگه داشته شود:

| مسیر | محتوا |
|---|---|
| `db.sqlite3` | کاربران، سفارش‌ها، پروفایل‌های رنگی، قیمت‌ها، تنظیمات |
| `media/` | تصاویر سفارش‌ها (نتیجه + اصل) |
| `uploads/` | فایل‌های موقت نشست‌های فعال |
| `.env` | کلید امنیتی و پیکربندی سرور |

`backup.sh` هر چهار مورد را در یک zip می‌گذارد. هیچ‌کدام در گیت نیستند.

---

## مستندات / Documentation

| سند | محتوا |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | سند نیازمندی‌های محصول: چرا، برای که، با چه قواعدی |
| [`docs/FEATURES.md`](docs/FEATURES.md) | فهرست کامل قابلیت‌ها و رفتار دقیق هرکدام |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | ساختار کد، مدل داده، API، تصمیم‌های فنی |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | نصب، پشتیبان‌گیری، بازیابی، عیب‌یابی |
| [`CHANGELOG.md`](CHANGELOG.md) | تاریخچهٔ تغییرات |

---

## مدل سه‌بعدی / 3D export

از صفحهٔ هر سفارش در پنل مدیریت، دکمهٔ **دانلود فایل STL**.

هر رنگ پالت یک پله می‌شود: لایهٔ ۱ به ارتفاع `x`، لایهٔ ۲ به `2x`، لایهٔ ۳ به
`3x` و … مقدار `x` («ارتفاع هر لایه»)، جهت آن و دقت مدل در **تنظیمات فروشگاه**
قابل تغییر است. ابعاد صفحه دقیقاً برابر اندازهٔ سفارش‌داده‌شدهٔ قاب است.

خروجی یک جسم بستهٔ manifold با نرمال‌های رو به بیرون است — آمادهٔ برش در هر
اسلایسر. جزئیات الگوریتم در [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## پشتهٔ فنی / Stack

- **Django 6** + **SQLite** — عمداً ساده، تا نگهداری و پشتیبان‌گیری آسان بماند
- **gunicorn** + **WhiteNoise** — بدون نیاز به nginx برای شروع
- **OpenCV / NumPy / scikit-image / Pillow** — موتور پردازش تصویر (`main.py`)
- **بدون فریم‌ورک جاوااسکریپت** — سه فایل ساده: `auth.js`، `app.js`، `style.css`
- **پنل مدیریت جنگو** — فارسی و راست‌به‌چپ به‌صورت داخلی

---

## امنیت / Security notes

- `PHOTO_FRAME_DEBUG=0` روی سرور عمومی الزامی است (پیش‌فرض `install.sh` همین است).
- برنامه روی HTTP خام اجرا می‌شود؛ برای سرویس واقعی، آن را پشت nginx با HTTPS قرار دهید.
- تصاویر سفارش‌ها خصوصی هستند و فقط برای صاحب سفارش و مدیران قابل دریافت‌اند.
- فایل‌های پشتیبان شامل `.env` و اطلاعات شخصی کاربران هستند — آن‌ها را امن نگه دارید.

---

## موتور پردازش به‌صورت مستقل / Standalone CLI

`main.py` مستقل از وب هم کار می‌کند:

```bash
.venv/bin/python main.py input.jpg output.png --num-levels 4 \
    --preprocess bilateral --postprocess connected_components
```
