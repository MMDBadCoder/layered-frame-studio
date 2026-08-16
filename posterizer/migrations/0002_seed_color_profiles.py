from django.db import migrations

# Starter palettes so the studio is usable the moment the site comes up.
# Colours run darkest -> lightest, matching layer 0 -> layer n-1.
SEED_PROFILES = [
    {
        "name": "سیاه و سفید کلاسیک",
        "description": "چهار لایهٔ خاکستری، مناسب برای بیشتر تصاویر",
        "sort_order": 1,
        "colors": ["#000000", "#555555", "#aaaaaa", "#ffffff"],
    },
    {
        "name": "سپیا",
        "description": "حال‌وهوای قدیمی و گرم",
        "sort_order": 2,
        "colors": ["#2b1d0e", "#6b4a24", "#b08750", "#f2e0c9"],
    },
    {
        "name": "آبی اقیانوس",
        "description": "پنج لایه با طیف آبی",
        "sort_order": 3,
        "colors": ["#0a1a2f", "#14375e", "#2f6690", "#74a9cf", "#d9eaf7"],
    },
    {
        "name": "غروب گرم",
        "description": "سه لایه با کنتراست بالا",
        "sort_order": 4,
        "colors": ["#2d0b1a", "#c2453f", "#ffd9a0"],
    },
    {
        "name": "چوب و طلا",
        "description": "مناسب قاب‌های چوبی",
        "sort_order": 5,
        "colors": ["#1b1208", "#4e341a", "#a8762c", "#f2d492"],
    },
]


def create_profiles(apps, schema_editor):
    ColorProfile = apps.get_model("posterizer", "ColorProfile")
    ProfileLayer = apps.get_model("posterizer", "ProfileLayer")

    for spec in SEED_PROFILES:
        if ColorProfile.objects.filter(name=spec["name"]).exists():
            continue

        profile = ColorProfile.objects.create(
            name=spec["name"],
            description=spec["description"],
            num_layers=len(spec["colors"]),
            sort_order=spec["sort_order"],
            is_active=True,
        )
        ProfileLayer.objects.bulk_create(
            [
                ProfileLayer(profile=profile, index=index, color=color)
                for index, color in enumerate(spec["colors"])
            ]
        )


def delete_profiles(apps, schema_editor):
    ColorProfile = apps.get_model("posterizer", "ColorProfile")
    ColorProfile.objects.filter(name__in=[spec["name"] for spec in SEED_PROFILES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("posterizer", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_profiles, delete_profiles),
    ]
