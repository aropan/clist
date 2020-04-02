# Generated by Django 2.2.10 on 2020-04-02 16:42

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('my_oauth', '0007_service_data_header'),
    ]

    operations = [
        migrations.AddField(
            model_name='token',
            name='access_token',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='token',
            name='data',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict),
        ),
    ]
