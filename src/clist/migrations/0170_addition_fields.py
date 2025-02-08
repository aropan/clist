# Generated by Django 5.1.5 on 2025-02-08 22:46

import django_add_default_value.add_default_value
from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [('clist', '0170_contest_upsolving_key_contest_upsolving_url'), ('clist', '0171_contest_raw_info'), ('clist', '0172_resource_has_statistic_n_first_ac_and_more'), ('clist', '0173_resource_has_account_last_submission'), ('clist', '0174_resource_has_statistic_total_solving'), ('clist', '0175_contest_has_statistic_upsolving'), ('clist', '0176_rename_has_statistic_upsolving_contest_has_unlimited_statistics'), ('clist', '0177_problem_name_ru'), ('clist', '0178_problem_name_en')]

    dependencies = [
        ('clist', '0169_contest_submissions_info'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='upsolving_key',
            field=models.CharField(blank=True, default=None, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='contest',
            name='upsolving_url',
            field=models.CharField(blank=True, default=None, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='contest',
            name='raw_info',
            field=models.JSONField(blank=True, default=dict),
        ),
        django_add_default_value.add_default_value.AddDefaultValue(
            model_name='contest',
            name='raw_info',
            value={},
        ),
        migrations.AddField(
            model_name='resource',
            name='has_statistic_n_first_ac',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resource',
            name='has_statistic_n_total_solved',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resource',
            name='has_account_last_submission',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='resource',
            name='has_statistic_total_solving',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='contest',
            name='has_unlimited_statistics',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='problem',
            name='name_ru',
            field=models.TextField(null=True),
        ),
        migrations.AddField(
            model_name='problem',
            name='name_en',
            field=models.TextField(null=True),
        ),
    ]
