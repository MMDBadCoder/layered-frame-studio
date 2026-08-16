# معماری — قاب عکس دوبعدی

---

## ۱. نمای کلی

```
مرورگر (بدون فریم‌ورک JS)
   │  fetch + FormData + X-CSRFToken
   ▼
gunicorn ──► Django 6 ──► SQLite (db.sqlite3)
   │            │
   │            ├─► main.py  ─► OpenCV / NumPy / scikit-image
   │            └─► media/   ─► تصاویر سفارش‌ها (خصوصی)
   │
   └─► WhiteNoise ─► staticfiles/
```

هیچ سرویس جانبی‌ای لازم نیست: بدون Redis، بدون Celery، بدون PostgreSQL،
بدون nginx (اختیاری). این عمدی است — نگهداری و پشتیبان‌گیری باید ساده بماند.

---

## ۲. ساختار پروژه

```
photoframe/          پروژهٔ جنگو: settings, urls, wsgi, asgi
accounts/            کاربر سفارشی و احراز هویت
  models.py          User با شماره موبایل به‌جای نام کاربری
  backends.py        ورود با شماره موبایل یا ایمیل
  validators.py      نرمال‌سازی ارقام فارسی و شماره موبایل
  forms.py           فرم‌های ورود و ثبت‌نام
  views.py           نقاط پایانی JSON برای modal
  management/commands/create_admin.py
posterizer/          استودیو، پروفایل‌ها، سفارش‌ها
  models.py          SiteSettings, ColorProfile, ProfileLayer, Order
  views.py           صفحه‌ها + API پردازش و ثبت سفارش
  admin.py           پنل مدیریت فارسی
  jalali.py          تاریخ شمسی، ارقام فارسی، قالب‌بندی تومان
  templatetags/      فیلترهای jalali، toman، cm، fa_digits
  management/commands/cleanup_uploads.py
main.py              موتور پردازش تصویر (مستقل از جنگو)
templates/           base, index, orders + partials
static/              style.css, auth.js, app.js
scripts/             install, uninstall, create-admin, backup, restore
```

---

## ۳. مدل داده

```
User (accounts)
 ├─ phone (یکتا، USERNAME_FIELD)
 ├─ email (یکتا)
 ├─ is_staff  → مدیر
 └─ is_superuser → مدیر کل

SiteSettings (تک‌نمونه، pk=1)
 ├─ min/max_width_cm، min/max_height_cm
 ├─ price_per_cm2
 └─ cost_rounding

ColorProfile
 ├─ name، description، num_layers، is_active، sort_order
 └─ layers → ProfileLayer(index، color)

Order
 ├─ user → User
 ├─ profile → ColorProfile (SET_NULL)
 ├─ snapshot: profile_name، num_layers، colors، config
 ├─ اندازه: width_cm، height_cm، area_cm2
 ├─ قیمت: price_per_cm2، estimated_cost، final_cost
 ├─ تصاویر: result_image، original_image
 └─ بررسی: status، admin_note، reviewed_by، reviewed_at
```

### چرا snapshot؟
سفارش باید برای همیشه همان چیزی را نشان دهد که مشتری سفارش داده است. اگر مدیر
بعداً رنگ‌های یک پروفایل یا قیمت هر cm² را عوض کند، سفارش‌های ثبت‌شده نباید
تغییر کنند. به همین دلیل نام پروفایل، رنگ‌ها، تنظیمات و قیمت داخل خود سفارش
کپی می‌شوند.

---

## ۴. نقاط پایانی

| مسیر | متد | توضیح |
|---|---|---|
| `/` | GET | استودیو (عمومی) |
| `/orders/` | GET | سفارش‌های من (نیازمند ورود) |
| `/orders/<id>/image/<kind>/` | GET | تصویر سفارش (صاحب سفارش یا مدیر) |
| `/api/config` | GET | تنظیمات پیش‌فرض، پروفایل‌ها، محدودهٔ اندازه |
| `/api/process` | POST | پردازش تصویر → data URL + محدودهٔ اندازه |
| `/api/orders/create` | POST | ثبت سفارش |
| `/api/auth/status` | GET | وضعیت ورود |
| `/api/auth/login` | POST | ورود |
| `/api/auth/register` | POST | ثبت‌نام |
| `/api/auth/logout` | POST | خروج |
| `/admin/` | — | پنل مدیریت |

همهٔ POSTها به هدر `X-CSRFToken` نیاز دارند. پاسخ‌های خطا شکل
`{"error": "پیام فارسی"}` دارند و پاسخ‌های احراز هویت `{"ok": bool, "errors": {...}}`.

---

## ۵. جریان پردازش تصویر

```
بایت‌های تصویر
   ↓ Pillow → آرایهٔ خاکستری
   ↓ پیش‌پردازش (گاوسی / میانه / دوطرفه)
   ↓ کوانتیزه به N سطح هم‌فاصله (N از پروفایل)
   ↓ پس‌پردازش (میانه / مورفولوژی / مؤلفه‌های همبند / اکثریت)
   ↓ نگاشت هر سطح به رنگ لایه (جدول ۲۵۶×۳)
PNG رنگی
```

`main.py` هیچ وابستگی‌ای به جنگو ندارد و مستقل هم قابل استفاده است.

### ذخیرهٔ موقت
- `uploads/<id>.bin` — تصویر اصلی نشست
- `uploads/<id>.result.png` — آخرین رندر

هنگام ثبت سفارش، اگر تنظیمات با آخرین رندر یکی باشد همان فایل استفاده می‌شود؛
وگرنه از نو پردازش می‌شود. این تضمین می‌کند سفارش دقیقاً همان چیزی است که
کاربر دیده.

---

## ۶. تصمیم‌های فنی مهم

| تصمیم | چرا |
|---|---|
| **SQLite** | یک فایل، پشتیبان‌گیری ساده، برای این حجم ترافیک کافی |
| **شماره موبایل به‌جای username** | مخاطب ایرانی؛ نام کاربری معنایی ندارد |
| **نشست پایگاه‌داده‌ای** | امکان ابطال نشست هنگام خروج |
| **modal به‌جای صفحهٔ ورود** | تصویر ساخته‌شده نباید گم شود (اصل شمارهٔ ۲ در PRD) |
| **پنل مدیریت جنگو** | فارسی و RTL آماده، مدیریت کاربر و مجوز رایگان |
| **WhiteNoise** | حذف نیاز به nginx برای شروع |
| **بدون فریم‌ورک JS** | سه فایل ساده؛ نگهداری در آینده آسان‌تر |
| **بدون نام‌گذاری hash روی فایل‌های ایستا** | نیازمند manifest است؛ فراموشی collectstatic نباید ۵۰۰ بدهد |
| **محاسبهٔ سمت سرور** | تعداد لایه، ارتفاع و قیمت هرگز از مرورگر پذیرفته نمی‌شوند |

---

## ۷. امنیت

- **CSRF** روی همهٔ POSTها؛ توکن جدید پس از ورود برگردانده می‌شود
- **محدودسازی ورود**: ۱۰ تلاش ناموفق در ۵ دقیقه به ازای هر IP
- **تصاویر خصوصی**: از طریق ویو با بررسی مالکیت، نه سرو مستقیم
- **حفظ نشست هنگام ورود**: `image_id` صریحاً منتقل می‌شود
- **اعتبارسنجی سمت سرور** برای تعداد لایه، اندازه و قیمت
- **`.env` با مجوز 600** و خارج از گیت
- **`DEBUG=0`** پیش‌فرض `install.sh`

### محدودیت‌های شناخته‌شده
- HTTP بدون TLS — برای تولید باید پشت nginx با HTTPS قرار گیرد
- سرویس با کاربر مالک پوشه اجرا می‌شود (روی این سرور: root)
- `ALLOWED_HOSTS = ["*"]`

---

## ۸. آزمون‌ها

```bash
.venv/bin/python manage.py test
```

۳۹ آزمون در `posterizer/tests.py`:

| کلاس | پوشش |
|---|---|
| `PublicStudioTests` | دسترسی مهمان، رنگ‌ها، اعتبارسنجی ورودی |
| `AuthTests` | ثبت‌نام، ورود، **حفظ تصویر هنگام ورود** |
| `OrderTests` | ثبت، سهمیهٔ ۳تایی، حریم خصوصی تصاویر |
| `FrameSizeAndCostTests` | نسبت، محدوده، قیمت، ضدّ دستکاری |
| `ColorProfileTests` | همگام‌سازی لایه‌ها، پروفایل غیرفعال |
| `AdminPanelTests` | دسترسی، تغییر وضعیت، عملیات گروهی |
