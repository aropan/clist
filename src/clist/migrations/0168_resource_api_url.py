# Generated by Django 5.1.4 on 2024-12-26 13:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0167_create_discussion'),
    ]

    operations = [
        migrations.AddField(
            model_name='resource',
            name='api_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
