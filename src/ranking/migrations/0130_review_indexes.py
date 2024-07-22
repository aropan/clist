# Generated by Django 4.2.11 on 2024-05-26 08:12

from django.db import migrations, models
import pyclist.indexes


class Migration(migrations.Migration):

    replaces = [('ranking', '0130_remove_account_ranking_acc_key_139169_gist_and_more'), ('ranking', '0131_account_ranking_acc_key_139169_gist_and_more'), ('ranking', '0132_rename_ranking_acc_resourc_c474c4_idx_resource_key_idx'), ('ranking', '0133_remove_account_ranking_acc_key_139169_gist_and_more'), ('ranking', '0134_alter_account_key'), ('ranking', '0135_remove_account_resource_key_idx_alter_account_key'), ('ranking', '0136_alter_account_key'), ('ranking', '0137_remove_account_ranking_acc_key_449bb8_gist_and_more'), ('ranking', '0138_account_ranking_acc_key_139169_gist_and_more')]

    dependencies = [
        ('ranking', '0129_module_delay_shortly_after'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_key_139169_gist',
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_name_26e7cf_gist',
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(db_index=True, max_length=1024),
        ),
        migrations.AddIndex(
            model_name='account',
            index=pyclist.indexes.GistIndexTrgrmOps(fields=['key'], name='ranking_acc_key_139169_gist'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=pyclist.indexes.GistIndexTrgrmOps(fields=['name'], name='ranking_acc_name_26e7cf_gist'),
        ),
        migrations.RenameIndex(
            model_name='account',
            new_name='resource_key_idx',
            old_name='ranking_acc_resourc_c474c4_idx',
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_key_139169_gist',
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(max_length=1024),
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(db_index=True, max_length=1024),
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='resource_key_idx',
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(max_length=1024),
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(db_index=True, max_length=1024),
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_key_449bb8_gist',
        ),
        migrations.RemoveIndex(
            model_name='account',
            name='ranking_acc_name_26e7cf_gist',
        ),
        migrations.AlterField(
            model_name='account',
            name='key',
            field=models.CharField(db_index=True, max_length=400),
        ),
        migrations.AlterField(
            model_name='account',
            name='name',
            field=models.CharField(blank=True, db_index=True, max_length=400, null=True),
        ),
        migrations.AddIndex(
            model_name='account',
            index=pyclist.indexes.GistIndexTrgrmOps(fields=['key'], name='ranking_acc_key_139169_gist'),
        ),
        migrations.AddIndex(
            model_name='account',
            index=pyclist.indexes.GistIndexTrgrmOps(fields=['name'], name='ranking_acc_name_26e7cf_gist'),
        ),
    ]
