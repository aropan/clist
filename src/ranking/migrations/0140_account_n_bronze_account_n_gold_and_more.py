# Generated by Django 5.1.5 on 2025-02-09 11:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0139_addition_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='n_bronze',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='n_gold',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='n_medal_contests',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='n_medals',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='n_other_medals',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='n_silver',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
    ]
