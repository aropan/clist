# Generated by Django 4.2.3 on 2023-07-30 21:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ranking', '0084_place_as_int_idx'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='statistics',
            name='ranking_sta_place_a_58facc_idx',
        ),
        migrations.AddIndex(
            model_name='statistics',
            index=models.Index(fields=['place_as_int', 'created'], name='ranking_sta_place_a_764576_idx'),
        ),
    ]
