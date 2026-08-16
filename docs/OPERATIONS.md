# راهنمای بهره‌برداری — قاب عکس دوبعدی

راهنمای عملی نصب، پشتیبان‌گیری، بازیابی و عیب‌یابی.

---

## ۱. نصب روی سرور تازه (اوبونتو)

```bash
git clone <repo-url> photo-frame-2d
cd photo-frame-2d
sudo ./scripts/install.sh
sudo ./scripts/create-admin.sh
```

`install.sh` این کارها را انجام می‌دهد:

1. نصب بسته‌های سیستمی لازم (`python3-venv`، `python3-pip`، `curl`)
2. ساخت `.venv` و نصب `requirements.txt`
3. ساخت `.env` با **کلید امنیتی تصادفی** (اگر وجود نداشته باشد)
4. اجرای مهاجرت‌ها و `collectstatic`
5. تنظیم مالکیت فایل‌های وضعیت
6. نوشتن و راه‌اندازی سرویس systemd
7. باز کردن پورت در ufw
8. بررسی سلامت با درخواست HTTP واقعی

### گزینه‌ها
```bash
sudo ./scripts/install.sh --port 9000      # پورت دیگر
sudo ./scripts/install.sh --host 127.0.0.1 # فقط لوکال (پشت nginx)
sudo ./scripts/install.sh --user www-data  # کاربر اجراکنندهٔ سرویس
sudo ./scripts/install.sh --debug          # حالت توسعه (روی سرور عمومی نزنید)
sudo ./scripts/install.sh --skip-apt       # بدون apt
```

### idempotent بودن
اجرای دوباره امن است: کلید امنیتی، پایگاه داده و تصاویر دست‌نخورده می‌مانند و
فقط وابستگی‌ها، مهاجرت‌ها، فایل‌های ایستا و فایل سرویس به‌روزرسانی می‌شوند.
از همین دستور برای **به‌روزرسانی پس از `git pull`** استفاده کنید.

---

## ۲. کار روزمره با سرویس

```bash
systemctl status photo-frame-2d          # وضعیت
systemctl restart photo-frame-2d         # راه‌اندازی مجدد
journalctl -u photo-frame-2d -f          # لاگ زنده
journalctl -u photo-frame-2d -n 100      # ۱۰۰ خط آخر
```

---

## ۳. پشتیبان‌گیری

```bash
./scripts/backup.sh                       # backups/photo-frame-2d-backup-<تاریخ>.zip
./scripts/backup.sh --output /mnt/nas/pf.zip
./scripts/backup.sh --keep 7              # فقط ۷ نسخهٔ آخر را نگه دار
./scripts/backup.sh --no-uploads          # بدون فایل‌های موقت (سبک‌تر)
./scripts/backup.sh --no-env              # بدون کلید امنیتی
```

### داخل فایل پشتیبان چیست؟
| مسیر | محتوا |
|---|---|
| `db.sqlite3` | کاربران، سفارش‌ها، پروفایل‌ها، قیمت‌ها، تنظیمات |
| `media/` | تصاویر سفارش‌ها |
| `uploads/` | رندرهای موقت نشست‌های فعال |
| `.env` | کلید امنیتی و پیکربندی |
| `manifest.json` | تاریخ، تعداد رکوردها، checksum پایگاه داده |

پایگاه داده با **SQLite online backup API** گرفته می‌شود، پس گرفتن پشتیبان
هنگام روشن بودن سرویس امن است و فایل نیمه‌نوشته نمی‌دهد.

> ⚠️ فایل پشتیبان شامل اطلاعات شخصی کاربران و کلید امنیتی است. آن را رمزگذاری
> یا در جای امن نگه دارید.

### پشتیبان‌گیری خودکار (cron)
```bash
sudo crontab -e
# هر شب ساعت ۳ بامداد، نگه‌داری ۱۴ نسخهٔ آخر
0 3 * * * /home/root/projects/Photo-Frame-2D/scripts/backup.sh --keep 14 --quiet
```

---

## ۴. بازیابی

```bash
./scripts/restore.sh --inspect backups/photo-frame-2d-backup-....zip   # فقط نمایش
sudo ./scripts/restore.sh backups/photo-frame-2d-backup-....zip        # بازیابی
```

مراحل خودکار:
1. اعتبارسنجی آرشیو و بررسی سلامت پایگاه داده
2. **گرفتن نسخهٔ ایمنی از وضعیت فعلی** (`backups/pre-restore-<تاریخ>.zip`)
3. توقف سرویس
4. جایگزینی پایگاه داده، `media/`، `uploads/` و `.env`
5. تنظیم مالکیت برای کاربر سرویس
6. اجرای مهاجرت‌ها (اگر پشتیبان قدیمی‌تر باشد)
7. راه‌اندازی سرویس و بررسی سلامت

### گزینه‌ها
```bash
--skip-env     # کلید امنیتی فعلی حفظ شود
--yes          # بدون پرسش تأیید (برای اسکریپت)
--no-safety    # بدون نسخهٔ ایمنی (توصیه نمی‌شود)
```

### انتقال به سرور جدید
```bash
# سرور قدیم
./scripts/backup.sh --output /tmp/move.zip
scp /tmp/move.zip newserver:/tmp/

# سرور جدید
git clone <repo-url> photo-frame-2d && cd photo-frame-2d
sudo ./scripts/install.sh
sudo ./scripts/restore.sh /tmp/move.zip --yes
```

---

## ۵. مدیریت کاربران

```bash
sudo ./scripts/create-admin.sh                      # تعاملی
sudo ./scripts/create-admin.sh \
    --phone 09121234567 --email a@b.com \
    --name "نام مدیر" --generate-password --noinput
```

اگر شماره از قبل وجود داشته باشد، همان حساب ارتقا می‌یابد و سفارش‌هایش
دست‌نخورده می‌ماند.

### تغییر رمز عبور
```bash
.venv/bin/python manage.py changepassword 09121234567
```

---

## ۶. حذف

```bash
sudo ./scripts/uninstall.sh                 # فقط سرویس؛ داده‌ها می‌مانند
sudo ./scripts/uninstall.sh --purge-venv    # + حذف .venv
sudo ./scripts/uninstall.sh --remove-ufw    # + حذف قانون فایروال
sudo ./scripts/uninstall.sh --purge-data    # + حذف همهٔ داده‌ها (تأیید می‌خواهد)
```

`--purge-data` قبل از حذف، خودکار یک پشتیبان می‌گیرد.

---

## ۷. نگهداری دوره‌ای

```bash
.venv/bin/python manage.py cleanup_uploads --days 7 --dry-run
.venv/bin/python manage.py cleanup_uploads --days 7
```

پوشهٔ `uploads/` رندرهای موقت نشست‌ها را نگه می‌دارد و به‌مرور بزرگ می‌شود.
تصاویر سفارش‌ها در `media/` هستند و **هرگز** توسط این دستور حذف نمی‌شوند.

پیشنهاد cron:
```
30 3 * * 0 /home/root/projects/Photo-Frame-2D/.venv/bin/python \
           /home/root/projects/Photo-Frame-2D/manage.py cleanup_uploads --days 7
```

---

## ۸. عیب‌یابی

| نشانه | بررسی |
|---|---|
| سرویس بالا نمی‌آید | `journalctl -u photo-frame-2d -n 50` |
| پورت اشغال است | `ss -ltnp \| grep 8080` |
| صفحه بدون استایل | `collectstatic` اجرا نشده → `sudo ./scripts/install.sh` |
| خطای ۴۰۳ روی درخواست‌ها | مشکل CSRF → کوکی‌ها را پاک و صفحه را تازه کنید |
| «تصویری یافت نشد» | فایل موقت نشست پاک شده → تصویر را دوباره بارگذاری کنید |
| قیمت اشتباه | پنل مدیریت ← تنظیمات فروشگاه ← قیمت هر سانتی‌متر مربع |
| کاربر نمی‌تواند سفارش دهد | سهمیهٔ ۳ سفارش بررسی‌نشده پر است |
| سوپرپیکسل غیرفعال | نیازمند `opencv-contrib-python-headless` |

### بازگشت سریع پس از اشتباه
```bash
ls -1t backups/pre-restore-*.zip | head -1     # آخرین نسخهٔ ایمنی
sudo ./scripts/restore.sh backups/pre-restore-....zip
```

---

## ۹. سخت‌سازی برای تولید

۱. **HTTPS**: پشت nginx با Let's Encrypt، و `install.sh --host 127.0.0.1`
۲. **فایروال**:
```bash
ufw allow OpenSSH      # اول این
ufw enable
```
۳. **`ALLOWED_HOSTS`**: در `photoframe/settings.py` به دامنهٔ واقعی محدود کنید
۴. **کاربر جداگانه**: `sudo ./scripts/install.sh --user www-data`
۵. **پشتیبان خارج از سرور**: فایل zip را به فضای ابری یا NAS منتقل کنید
