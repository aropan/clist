# Generated by Django 2.2.10 on 2020-02-14 01:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0026_auto_20200214_0051'),
    ]

    operations = [
        migrations.AddField(
            model_name='autorating',
            name='time_to_update',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
