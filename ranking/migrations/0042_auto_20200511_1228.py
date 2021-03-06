# Generated by Django 2.2.10 on 2020-05-11 22:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0041_account_rating'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_resourc_fe9bbc_idx',
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_resourc_c26e26_idx',
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_resourc_23c237_idx',
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'country', 'id'], name='ranking_acc_resourc_61bc33_idx'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'n_contests', 'id'], name='ranking_acc_resourc_6766dc_idx'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'last_activity', 'id'], name='ranking_acc_resourc_182b8f_idx'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'rating', 'id'], name='ranking_acc_resourc_407632_idx'),
        ),
    ]
