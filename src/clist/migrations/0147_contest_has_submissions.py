# Generated by Django 4.2.11 on 2024-05-04 16:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0146_contest_merging_contests'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='has_submissions',
            field=models.BooleanField(blank=True, db_index=True, default=None, null=True),
        ),
    ]
