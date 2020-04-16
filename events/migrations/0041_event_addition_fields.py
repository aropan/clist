# Generated by Django 2.2.10 on 2020-04-16 18:07

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0040_event_team_size'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='addition_fields',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict),
        ),
    ]
