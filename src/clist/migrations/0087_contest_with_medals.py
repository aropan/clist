# Generated by Django 3.1.14 on 2022-12-25 10:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0086_contest_registration_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='with_medals',
            field=models.BooleanField(blank=True, db_index=True, default=None, null=True),
        ),
    ]
