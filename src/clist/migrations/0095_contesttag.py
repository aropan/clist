# Generated by Django 3.1.14 on 2023-03-05 01:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0094_auto_20230122_0447'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContestTag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('name', models.TextField(db_index=True, unique=True)),
                ('short', models.TextField(db_index=True, unique=True)),
                ('slug', models.TextField(blank=True, db_index=True, unique=True)),
                ('contests', models.ManyToManyField(blank=True, related_name='tags', to='clist.Contest')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]