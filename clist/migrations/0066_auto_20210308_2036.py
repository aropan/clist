# Generated by Django 3.1.7 on 2021-03-08 20:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0065_auto_20210308_1502'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='problem',
            index=models.Index(fields=['resource_id', 'url', '-time', 'contest_id', 'index'], name='clist_probl_resourc_b20e6c_idx'),
        ),
        migrations.AddIndex(
            model_name='problem',
            index=models.Index(fields=['-time', 'contest_id', 'index'], name='clist_probl_time_fe6a53_idx'),
        ),
    ]
