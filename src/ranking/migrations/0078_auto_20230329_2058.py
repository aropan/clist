# Generated by Django 3.1.14 on 2023-03-29 20:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0077_auto_20221226_2005'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='account',
            index=models.Index(fields=['resource', 'updated'], name='ranking_acc_resourc_d3d8b4_idx'),
        ),
    ]
