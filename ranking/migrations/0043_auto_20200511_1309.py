# Generated by Django 2.2.10 on 2020-05-11 23:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0042_auto_20200511_1228'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_resourc_182b8f_idx',
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'last_activity', '-id'], name='ranking_acc_resourc_f2088d_idx'),
        ),
    ]
