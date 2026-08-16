"""Helpers for normalising Persian input (digits, phone numbers)."""

import re

from django.core.exceptions import ValidationError

# Persian (۰-۹) and Arabic-Indic (٠-٩) digits mapped onto ASCII, because people
# routinely type phone numbers with their keyboard's native numerals.
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_PHONE_RE = re.compile(r"^09\d{9}$")


def normalize_digits(value: str) -> str:
    """Convert Persian/Arabic numerals in a string to ASCII digits."""
    return (value or "").translate(_DIGIT_MAP)


def normalize_phone(value: str) -> str:
    """
    Normalise an Iranian mobile number to the canonical 09xxxxxxxxx form.

    Accepts +989xxxxxxxxx, 00989xxxxxxxxx, 989xxxxxxxxx, 9xxxxxxxxx and
    09xxxxxxxxx, with or without spaces/dashes and in any numeral system.
    """
    digits = normalize_digits(value).strip()
    digits = re.sub(r"[\s\-()._]", "", digits)

    if digits.startswith("+98"):
        digits = "0" + digits[3:]
    elif digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "0" + digits

    if not _PHONE_RE.match(digits):
        raise ValidationError("شماره موبایل معتبر نیست. نمونهٔ درست: ۰۹۱۲۳۴۵۶۷۸۹")

    return digits


def validate_phone(value: str) -> None:
    """Model-level validator; keeps the canonical form as the only valid one."""
    if not _PHONE_RE.match(normalize_digits(value or "")):
        raise ValidationError("شماره موبایل باید ۱۱ رقم و به شکل ۰۹۱۲۳۴۵۶۷۸۹ باشد.")
