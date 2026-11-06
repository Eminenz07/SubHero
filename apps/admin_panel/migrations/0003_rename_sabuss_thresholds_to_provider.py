from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0002_alertconfig_ogaviral_critical_threshold_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="alertconfig",
            old_name="sabuss_warning_threshold",
            new_name="provider_warning_threshold",
        ),
        migrations.RenameField(
            model_name="alertconfig",
            old_name="sabuss_critical_threshold",
            new_name="provider_critical_threshold",
        ),
        migrations.RemoveField(
            model_name="alertconfig",
            name="cdh_warning_threshold",
        ),
        migrations.RemoveField(
            model_name="alertconfig",
            name="cdh_critical_threshold",
        ),
        migrations.AlterField(
            model_name="alertconfig",
            name="provider_warning_threshold",
            field=models.DecimalField(decimal_places=2, default=10000.0, max_digits=12),
        ),
        migrations.AlterField(
            model_name="alertconfig",
            name="provider_critical_threshold",
            field=models.DecimalField(decimal_places=2, default=3000.0, max_digits=12),
        ),
    ]
