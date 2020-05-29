# Generated by Django 2.2.10 on 2020-05-28 23:03

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0035_auto_20200503_0128'),
        ('ranking', '0048_auto_20200513_2224'),
    ]

    operations = [
        migrations.CreateModel(
            name='Problem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('modified', models.DateTimeField(auto_now=True)),
                ('key', models.TextField()),
                ('name', models.TextField()),
                ('short', models.TextField(blank=True, default=None, null=True)),
                ('url', models.TextField(blank=True, default=None, null=True)),
                ('n_tries', models.IntegerField(blank=True, default=None, null=True)),
                ('n_accepted', models.IntegerField(blank=True, default=None, null=True)),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='clist.Contest')),
            ],
            options={
                'unique_together': {('contest', 'key')},
            },
        ),
    ]
