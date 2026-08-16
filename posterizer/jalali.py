"""Gregorian → Jalali (Solar Hijri) conversion and Persian numeral helpers.

Self-contained so the project keeps its dependency list unchanged.
"""

_LATIN_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

_GREGORIAN_DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def to_persian_digits(value) -> str:
    return str(value).translate(_LATIN_TO_PERSIAN)


def format_toman(value) -> str:
    """۱٬۲۳۴٬۰۰۰ تومان — grouped with the Persian thousands separator."""
    if value is None:
        return "—"
    grouped = f"{int(value):,}".replace(",", "٬")
    return f"{to_persian_digits(grouped)} تومان"


def format_cm(value) -> str:
    """Trim trailing zeros so 30.0 reads as ۳۰ but 30.5 keeps its decimal."""
    if value is None:
        return "—"
    text = f"{float(value):g}"
    return to_persian_digits(text)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to the Solar Hijri calendar."""
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + _GREGORIAN_DAYS_BEFORE_MONTH[gm - 1]
    )

    jy += 33 * (days // 12053)
    days %= 12053

    jy += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30

    return jy, jm, jd


def format_jalali(value, with_time: bool = True, month_name: bool = False) -> str:
    """Format an aware/naive datetime (or date) as a Persian date string."""
    if value is None:
        return "—"

    from django.utils import timezone

    if hasattr(value, "hour"):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
    jy, jm, jd = gregorian_to_jalali(value.year, value.month, value.day)

    if month_name:
        date_part = f"{jd} {MONTH_NAMES[jm - 1]} {jy}"
    else:
        date_part = f"{jy}/{jm:02d}/{jd:02d}"

    if with_time and hasattr(value, "hour"):
        date_part = f"{date_part} — {value.hour:02d}:{value.minute:02d}"

    return to_persian_digits(date_part)
