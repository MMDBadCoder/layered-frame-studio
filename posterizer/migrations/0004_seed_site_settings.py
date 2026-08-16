from django.db import migrations


def create_settings(apps, schema_editor):
    """Make sure the singleton row exists so the admin page is never empty."""
    SiteSettings = apps.get_model("posterizer", "SiteSettings")
    SiteSettings.objects.get_or_create(pk=1)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posterizer", "0003_sitesettings_order_area_cm2_order_estimated_cost_and_more"),
    ]

    operations = [
        migrations.RunPython(create_settings, noop),
    ]
