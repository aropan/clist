# Generated by Django 3.1.14 on 2022-07-03 22:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notification', '0029_notification_with_virtual'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='with_virtual',
            field=models.BooleanField(default=False),
        ),
    ]
