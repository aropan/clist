# Generated by Django 4.2.3 on 2023-09-22 19:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0091_remove_account_ranking_acc_resourc_65aa35_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='module',
            name='long_contest_idle',
            field=models.DurationField(blank=True, default='06:00:00'),
        ),
    ]
