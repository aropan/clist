# Generated by Django 2.2.10 on 2020-04-16 19:03

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0044_auto_20200416_1903'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='fields_info',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict),
        ),
    ]
