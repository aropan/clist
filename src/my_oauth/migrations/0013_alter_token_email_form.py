# Generated by Django 5.1 on 2024-10-27 12:44

import uuid

import autoslug.fields
import django.db.models.deletion
from django.db import migrations, models

import my_oauth.models


class Migration(migrations.Migration):

    dependencies = [
        ('my_oauth', '0012_auto_20220211_2316'),
    ]

    operations = [
        migrations.AlterField(
            model_name='token',
            name='email',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.CreateModel(
            name='Form',
            fields=[
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('slug', autoslug.fields.AutoSlugField(editable=False, populate_from='name', unique=True)),
                ('code', models.TextField()),
                ('secret', models.CharField(default=my_oauth.models.generate_secret_64, max_length=64, unique=True)),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='my_oauth.service')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
