"""
Replace `stl_invert_heights` with `stl_dark_is_tallest`, defaulting to True.

The old flag shipped with default False, which built the plate with the
DARKEST colour shortest and the lightest tallest. That is backwards for a
layered frame: the dark areas are the deep ones. The setting is therefore
re-expressed positively — "the darkest layer is the tallest" — and defaults to
on.

The previous value is deliberately NOT carried over. It was never a considered
choice; it was a wrong default that nobody had reason to change, so every
existing installation moves to the corrected behaviour. Anyone who genuinely
wants light-tallest can untick the new box.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posterizer", "0007_alter_sitesettings_ai_helper_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="stl_dark_is_tallest",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "روشن باشد: نواحی تیره بیشترین ارتفاع و نواحی روشن کمترین ارتفاع را دارند "
                    "(حالت متداول برای قاب‌های لایه‌ای). خاموش باشد: برعکس."
                ),
                verbose_name="تیره‌ترین لایه بلندترین باشد",
            ),
        ),
        migrations.RemoveField(
            model_name="sitesettings",
            name="stl_invert_heights",
        ),
    ]
