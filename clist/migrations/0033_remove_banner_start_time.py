# Generated by Django 2.2.10 on 2020-03-25 22:50

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0032_auto_20200325_2216'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='banner',
            name='start_time',
        ),
    ]