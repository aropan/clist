# Generated by Django 2.2.13 on 2020-11-22 19:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0052_n_statistics'),
    ]

    operations = [
        migrations.AddField(
            model_name='resource',
            name='avatar_url',
            field=models.CharField(blank=True, default=None, max_length=255, null=True),
        ),
    ]
