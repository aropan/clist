# Generated by Django 2.2.13 on 2021-02-26 20:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('my_oauth', '0008_auto_20200402_1642'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='disable',
            field=models.BooleanField(default=False),
        ),
    ]
