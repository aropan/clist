# Generated by Django 3.1.14 on 2022-07-31 22:59

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('true_coders', '0050_auto_20220320_2231'),
        ('ranking', '0069_auto_20220728_2257'),
        ('clist', '0086_contest_registration_url'),
        ('notification', '0035_auto_20220731_1951'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='subscription',
            unique_together={('coder', 'method', 'contest', 'account')},
        ),
    ]
