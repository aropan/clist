# Generated by Django 4.2.3 on 2023-09-17 07:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0117_alter_resource_n_rating_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='problem',
            name='archive_url',
            field=models.TextField(blank=True, default=None, null=True),
        ),
    ]
