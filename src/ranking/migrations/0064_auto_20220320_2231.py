# Generated by Django 3.1.14 on 2022-03-20 22:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0063_auto_20210828_2200'),
    ]

    operations = [
        migrations.AddField(
            model_name='statistics',
            name='global_rating_change',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='statistics',
            name='new_global_rating',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
    ]