# Generated by Django 3.1.14 on 2022-12-26 16:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0074_auto_20221226_1537'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='statistics',
            index=models.Index(fields=['contest', 'advanced'], name='ranking_sta_contest_87998c_idx'),
        ),
        migrations.AddIndex(
            model_name='statistics',
            index=models.Index(fields=['account', 'advanced'], name='ranking_sta_account_226235_idx'),
        ),
    ]
