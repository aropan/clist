# Generated by Django 4.2.3 on 2023-11-01 22:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0126_alter_contest_has_fixed_rating_prediction_field'),
    ]

    operations = [
        migrations.AddField(
            model_name='resource',
            name='has_standings_renamed_account',
            field=models.BooleanField(default=False),
        ),
    ]
