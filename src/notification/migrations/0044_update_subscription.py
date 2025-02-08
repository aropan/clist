# Generated by Django 5.1.5 on 2025-02-08 22:48

import django.contrib.postgres.fields
import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):

    replaces = [('notification', '0044_subscription_scopes'), ('notification', '0045_alter_subscription_scopes'), ('notification', '0046_subscription_notificatio_scopes_2042f8_gin'), ('notification', '0047_remove_subscription_notificatio_enable_2370eb_idx_and_more')]

    dependencies = [
        ('clist', '0169_contest_submissions_info'),
        ('notification', '0043_subscription_with_custom_names'),
        ('ranking', '0139_account_n_listvalues'),
        ('tg', '0013_chat_accounts'),
        ('true_coders', '0075_coderlist_account_update_delay'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='scopes',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.PositiveSmallIntegerField(choices=[(1, 'Statistics'), (2, 'Upsolving')]), blank=True, default=list, size=None),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=django.contrib.postgres.indexes.GinIndex(fields=['scopes'], name='notificatio_scopes_2042f8_gin'),
        ),
        migrations.RemoveIndex(
            model_name='subscription',
            name='notificatio_enable_2370eb_idx',
        ),
        migrations.RemoveIndex(
            model_name='subscription',
            name='notificatio_scopes_2042f8_gin',
        ),
        migrations.RemoveField(
            model_name='subscription',
            name='scopes',
        ),
        migrations.AddField(
            model_name='subscription',
            name='with_statistics',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='subscription',
            name='with_upsolving',
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['enable', 'resource', 'contest', 'with_statistics'], name='notificatio_enable_1e3666_idx'),
        ),
        migrations.AddIndex(
            model_name='subscription',
            index=models.Index(fields=['enable', 'resource', 'contest', 'with_upsolving'], name='notificatio_enable_5054e0_idx'),
        ),
    ]
