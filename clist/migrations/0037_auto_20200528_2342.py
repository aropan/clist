# Generated by Django 2.2.10 on 2020-05-28 23:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0036_problem'),
    ]

    operations = [
        migrations.AlterField(
            model_name='problem',
            name='index',
            field=models.SmallIntegerField(null=True),
        ),
    ]
