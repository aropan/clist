# Generated by Django 2.2.10 on 2020-02-14 01:12

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0027_autorating_time_to_update'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='autorating',
            name='time_to_update',
        ),
    ]
