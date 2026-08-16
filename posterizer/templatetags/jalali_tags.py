from django import template

from ..jalali import format_cm, format_jalali, format_toman, to_persian_digits

register = template.Library()


@register.filter(name="toman")
def toman(value):
    """۱٬۲۳۴٬۰۰۰ تومان"""
    return format_toman(value)


@register.filter(name="cm")
def cm(value):
    return format_cm(value)


@register.filter(name="jalali")
def jalali(value):
    """۱۴۰۴/۰۵/۲۵ — ۲۰:۳۰"""
    return format_jalali(value, with_time=True)


@register.filter(name="jalali_date")
def jalali_date(value):
    """۲۵ مرداد ۱۴۰۴"""
    return format_jalali(value, with_time=False, month_name=True)


@register.filter(name="fa_digits")
def fa_digits(value):
    return to_persian_digits(value)
