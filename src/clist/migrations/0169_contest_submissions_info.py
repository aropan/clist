# Generated by Django 5.1.4 on 2024-12-28 12:50

import django_add_default_value.add_default_value
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0168_resource_api_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='submissions_info',
            field=models.JSONField(blank=True, default=dict),
        ),
        django_add_default_value.add_default_value.AddDefaultValue(
            model_name='contest',
            name='submissions_info',
            value={},
        ),
    ]