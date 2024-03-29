# Generated by Django 3.1.12 on 2021-07-03 23:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notification', '0015_auto_20210308_1449'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='created',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='modified',
            field=models.DateTimeField(auto_now=True, db_index=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='created',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='modified',
            field=models.DateTimeField(auto_now=True, db_index=True),
        ),
    ]
