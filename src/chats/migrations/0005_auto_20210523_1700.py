# Generated by Django 3.1.8 on 2021-05-23 17:00

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0004_auto_20210523_1656'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='ChatHistory',
            new_name='ChatLog',
        ),
    ]
