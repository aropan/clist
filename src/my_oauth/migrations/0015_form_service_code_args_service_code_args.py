# Generated by Django 5.1.3 on 2024-12-08 11:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('my_oauth', '0014_forms'),
    ]

    operations = [
        migrations.AddField(
            model_name='form',
            name='service_code_args',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='service',
            name='code_args',
            field=models.TextField(blank=True),
        ),
    ]
