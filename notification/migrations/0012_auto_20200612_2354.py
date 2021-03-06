# Generated by Django 2.2.13 on 2020-06-12 23:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notification', '0011_auto_20200612_2345'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='secret',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='message',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='subject',
            field=models.CharField(blank=True, max_length=4096, null=True),
        ),
    ]
