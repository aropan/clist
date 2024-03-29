# Generated by Django 3.1.8 on 2021-05-23 16:29

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Chat',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('chat_type', models.CharField(choices=[('ROOM', 'Room'), ('PRIV', 'Private')], default='ROOM', max_length=4)),
                ('name', models.TextField()),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
