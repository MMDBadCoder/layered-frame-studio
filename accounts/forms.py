from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from .validators import normalize_digits, normalize_phone

User = get_user_model()


class RegisterForm(forms.Form):
    """Sign-up form used by the modal (submitted as JSON/FormData)."""

    full_name = forms.CharField(
        label="نام و نام خانوادگی",
        max_length=150,
        required=False,
        error_messages={"max_length": "نام وارد شده بیش از حد طولانی است."},
    )
    phone = forms.CharField(
        label="شماره موبایل",
        error_messages={"required": "وارد کردن شماره موبایل الزامی است."},
    )
    email = forms.EmailField(
        label="ایمیل",
        error_messages={
            "required": "وارد کردن ایمیل الزامی است.",
            "invalid": "ایمیل وارد شده معتبر نیست.",
        },
    )
    password1 = forms.CharField(
        label="رمز عبور",
        error_messages={"required": "وارد کردن رمز عبور الزامی است."},
    )
    password2 = forms.CharField(
        label="تکرار رمز عبور",
        error_messages={"required": "تکرار رمز عبور الزامی است."},
    )

    def clean_full_name(self):
        return (self.cleaned_data.get("full_name") or "").strip()

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if User.objects.filter(phone=phone).exists():
            raise ValidationError("این شماره موبایل قبلاً ثبت شده است. وارد شوید.")
        return phone

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("این ایمیل قبلاً ثبت شده است. وارد شوید.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "رمز عبور و تکرار آن یکسان نیستند.")
        elif password1:
            candidate = User(
                phone=cleaned.get("phone") or "",
                email=cleaned.get("email") or "",
                full_name=cleaned.get("full_name") or "",
            )
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)

        return cleaned

    def save(self) -> User:
        return User.objects.create_user(
            phone=self.cleaned_data["phone"],
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            full_name=self.cleaned_data["full_name"],
        )


class LoginForm(forms.Form):
    """Sign-in form: one field accepting a phone number or an email."""

    identifier = forms.CharField(
        label="شماره موبایل یا ایمیل",
        error_messages={"required": "شماره موبایل یا ایمیل خود را وارد کنید."},
    )
    password = forms.CharField(
        label="رمز عبور",
        error_messages={"required": "وارد کردن رمز عبور الزامی است."},
    )

    def clean_identifier(self):
        return normalize_digits(self.cleaned_data["identifier"]).strip()
