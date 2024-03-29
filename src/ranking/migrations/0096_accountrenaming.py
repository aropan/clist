# Generated by Django 4.2.3 on 2023-10-14 21:31

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0126_alter_contest_has_fixed_rating_prediction_field'),
        ('ranking', '0095_module_enable'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountRenaming',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('old_key', models.CharField(max_length=1024)),
                ('new_key', models.CharField(max_length=1024)),
                ('resource', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='clist.resource')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
