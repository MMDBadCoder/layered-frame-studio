"""
Create (or promote) a super admin.

Django's own createsuperuser works, but this one speaks the project's language:
it validates Iranian phone numbers, accepts Persian digits, and can promote an
existing customer account without disturbing their orders.

    python manage.py create_admin
    python manage.py create_admin --phone 09121234567 --email a@b.com --password ... --noinput
    python manage.py create_admin --phone 09121234567 --generate-password
"""

import getpass
import secrets
import string
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts.validators import normalize_phone

User = get_user_model()


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "ساخت یا ارتقای یک کاربر به مدیر کل (super admin)"

    def add_arguments(self, parser):
        parser.add_argument("--phone", help="شماره موبایل، مثل 09121234567")
        parser.add_argument("--email", help="ایمیل مدیر")
        parser.add_argument("--name", default="", help="نام و نام خانوادگی")
        parser.add_argument("--password", help="رمز عبور (ناامن در تاریخچهٔ شل)")
        parser.add_argument(
            "--generate-password", action="store_true", help="یک رمز تصادفی بساز و نمایش بده"
        )
        parser.add_argument(
            "--noinput", "--no-input", action="store_true", dest="noinput",
            help="بدون پرسش تعاملی اجرا شود",
        )

    def prompt(self, label: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            value = input(f"{label}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise CommandError("لغو شد.")
        return value or default

    def handle(self, *args, **options):
        interactive = not options["noinput"] and sys.stdin.isatty()

        # --- phone ---
        phone_raw = options.get("phone")
        if not phone_raw and interactive:
            phone_raw = self.prompt("شماره موبایل")
        if not phone_raw:
            raise CommandError("شماره موبایل الزامی است (--phone).")

        try:
            phone = normalize_phone(phone_raw)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))

        existing = User.objects.filter(phone=phone).first()

        # --- email ---
        email = options.get("email") or (existing.email if existing else "")
        if not email and interactive:
            email = self.prompt("ایمیل")
        if not email:
            raise CommandError("ایمیل الزامی است (--email).")
        email = email.strip().lower()

        clash = User.objects.filter(email__iexact=email).exclude(phone=phone).first()
        if clash:
            raise CommandError(f"این ایمیل قبلاً برای شمارهٔ {clash.phone} ثبت شده است.")

        # --- name ---
        name = options.get("name") or (existing.full_name if existing else "")
        if not name and interactive:
            name = self.prompt("نام و نام خانوادگی (اختیاری)")

        # --- password ---
        password = options.get("password")
        generated = False

        if options["generate_password"]:
            password = generate_password()
            generated = True
        elif not password and interactive:
            while True:
                password = getpass.getpass("رمز عبور: ")
                if not password:
                    self.stderr.write("رمز عبور نمی‌تواند خالی باشد.")
                    continue
                if password != getpass.getpass("تکرار رمز عبور: "):
                    self.stderr.write("رمزها یکسان نیستند؛ دوباره تلاش کنید.")
                    continue
                break
        elif not password:
            if existing:
                password = None  # promoting only, keep the current password
            else:
                password = generate_password()
                generated = True

        candidate = existing or User(phone=phone, email=email, full_name=name)
        if password:
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                if generated:
                    pass  # random 16-char passwords are fine by construction
                else:
                    raise CommandError("رمز عبور ضعیف است: " + " ".join(exc.messages))

        # --- create or promote ---
        if existing:
            existing.email = email
            existing.full_name = name or existing.full_name
            existing.is_staff = True
            existing.is_superuser = True
            existing.is_active = True
            if password:
                existing.set_password(password)
            existing.save()
            user, action = existing, "ارتقا یافت"
        else:
            user = User.objects.create_superuser(
                phone=phone, email=email, password=password, full_name=name
            )
            action = "ساخته شد"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"کاربر مدیر {action}."))
        self.stdout.write(f"  شماره موبایل : {user.phone}")
        self.stdout.write(f"  ایمیل        : {user.email}")
        self.stdout.write(f"  نام          : {user.full_name or '—'}")
        if generated:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"  رمز عبور     : {password}"))
            self.stdout.write("  این رمز فقط همین یک بار نمایش داده می‌شود؛ آن را ذخیره کنید.")
        elif not password:
            self.stdout.write("  رمز عبور     : بدون تغییر")
        self.stdout.write("")
