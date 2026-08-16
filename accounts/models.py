from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from .validators import normalize_phone, validate_phone


class UserManager(BaseUserManager):
    """Manager for a user identified by phone number instead of a username."""

    use_in_migrations = True

    def _create_user(self, phone, email, password, **extra_fields):
        if not phone:
            raise ValueError("شماره موبایل الزامی است.")
        if not email:
            raise ValueError("ایمیل الزامی است.")

        phone = normalize_phone(phone)
        email = self.normalize_email(email).lower()

        user = self.model(phone=phone, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, phone, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone, email, password, **extra_fields)

    def create_superuser(self, phone, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("کاربر مدیر باید is_staff=True داشته باشد.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("ابرکاربر باید is_superuser=True داشته باشد.")

        return self._create_user(phone, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Site user.

    Two tiers, as required: ordinary users (is_staff=False) who submit orders,
    and admins (is_staff=True) who review them in the admin panel.
    """

    phone = models.CharField(
        "شماره موبایل",
        max_length=11,
        unique=True,
        validators=[validate_phone],
        help_text="به شکل ۰۹۱۲۳۴۵۶۷۸۹",
    )
    email = models.EmailField("ایمیل", unique=True)
    full_name = models.CharField("نام و نام خانوادگی", max_length=150, blank=True)

    is_active = models.BooleanField("فعال", default=True)
    is_staff = models.BooleanField(
        "مدیر",
        default=False,
        help_text="اگر فعال باشد، کاربر به پنل مدیریت دسترسی دارد.",
    )
    date_joined = models.DateTimeField("تاریخ عضویت", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["email"]

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.full_name or self.phone

    def save(self, *args, **kwargs):
        if self.phone:
            self.phone = normalize_phone(self.phone)
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name or self.phone

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.phone

    @property
    def display_name(self):
        """What the header shows once someone is signed in."""
        return self.full_name or self.phone

    @property
    def role_label(self):
        return "مدیر" if self.is_staff else "کاربر عادی"
