# Generated by Django 5.1 on 2024-11-17 15:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('true_coders', '0069_listvalue_true_coders_coder_l_1cff61_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='coder',
            name='n_subscribers',
            field=models.IntegerField(blank=True, db_index=True, default=0),
        ),
    ]
