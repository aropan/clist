# -*- coding: utf-8 -*-
# Generated by Django 1.11.10 on 2018-04-02 03:43


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0002_auto_20180402_0255'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='title',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
