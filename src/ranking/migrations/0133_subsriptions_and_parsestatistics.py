# Generated by Django 5.1 on 2024-11-17 15:29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [('ranking', '0133_remove_account_is_subscribed_account_n_subsriptions'), ('ranking', '0134_rename_n_subsriptions_account_n_subscriptions'), ('ranking', '0135_alter_account_n_subscriptions'), ('ranking', '0136_rename_n_subscriptions_account_n_subscribers'), ('ranking', '0137_parsestatistics'), ('ranking', '0138_rename_parsestatistics_parsestatistic'), ('ranking', '0139_rename_parsestatistic_parsestatistics_and_more'), ('ranking', '0140_parsestatistics_parse_time')]

    dependencies = [
        ('clist', '0167_rename_inherit_medals_to_related_resource_has_inherit_medals_to_related'),
        ('ranking', '0132_account_rating_prediction'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='account',
            name='is_subscribed',
        ),
        migrations.AddField(
            model_name='account',
            name='n_subscribers',
            field=models.IntegerField(blank=True, db_index=True, default=0),
        ),
        migrations.CreateModel(
            name='ParseStatistics',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('delay', models.DurationField(blank=True, null=True)),
                ('enable', models.BooleanField(blank=True, default=True)),
                ('without_set_coder_problems', models.BooleanField(blank=True, default=True)),
                ('without_stage', models.BooleanField(blank=True, default=True)),
                ('without_subscriptions', models.BooleanField(blank=True, default=False)),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='clist.contest')),
                ('parse_time', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'abstract': False,
                'verbose_name_plural': 'ParseStatistics',
            },
        ),
    ]
