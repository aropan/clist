# Generated by Django 2.2.13 on 2020-10-10 02:35

from django.db import migrations
import pyclist.indexes


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0054_auto_20201008_2303'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='account',
            index=pyclist.indexes.GistIndexTrgrmOps(fields=['name'], name='ranking_acc_name_26e7cf_gist'),
        ),
    ]
