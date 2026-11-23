"""Platform contact point becomes a fixed code instead of a user FK.
Existing requests keep the code (username) they were submitted with."""
from django.db import migrations, models

import reports.models


def copy_codes(apps, schema_editor):
    ActionRequest = apps.get_model("reports", "ActionRequest")
    for r in ActionRequest.objects.select_related("platform_contact").only("pk", "platform_contact__username"):
        ActionRequest.objects.filter(pk=r.pk).update(platform_contact_code=r.platform_contact.username)


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0002_profile_videos_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="actionrequest",
            name="platform_contact_code",
            field=models.CharField(
                default=reports.models.default_platform_contact_code, editable=False, max_length=32,
                verbose_name="مسؤول المنصة (نقطة الاتصال) - الكود",
            ),
        ),
        migrations.RunPython(copy_codes, migrations.RunPython.noop),
        migrations.RemoveField(model_name="actionrequest", name="platform_contact"),
    ]
