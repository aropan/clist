# Generated by Django 4.2.3 on 2023-08-20 18:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('true_coders', '0055_filter_start_time_from_filter_start_time_to'),
    ]

    operations = [
        migrations.AlterField(
            model_name='filter',
            name='start_time_from',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='filter',
            name='start_time_to',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
