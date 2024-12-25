# Generated by Django 5.1.4 on 2024-12-25 22:42

import django.db.models.deletion
from django.db import migrations, models


def set_new_group(apps, schema_editor):
    ListValue = apps.get_model('true_coders', 'ListValue')
    ListGroup = apps.get_model('true_coders', 'ListGroup')

    new_groups = {}
    for lv in ListValue.objects.filter(new_group__isnull=False):
        key = (lv.coder_list_id, lv.group_id)
        new_groups[key] = lv.new_group

    for lv in ListValue.objects.filter(new_group__isnull=True):
        key = (lv.coder_list_id, lv.group_id)
        if key not in new_groups:
            new_groups[key] = ListGroup.objects.create(coder_list_id=lv.coder_list_id)
        lv.new_group = new_groups[key]
        lv.save(update_fields=['new_group'])


class Migration(migrations.Migration):

    replaces = [('true_coders', '0071_listgroup_listvalue_new_group'), ('true_coders', '0072_remove_listvalue_unique_account_and_more'), ('true_coders', '0073_alter_listvalue_group'), ('true_coders', '0074_listgroup_name'), ('true_coders', '0075_coderlist_with_names'), ('true_coders', '0076_coderproblem_time_coderproblem_upsolving_and_more'), ('true_coders', '0077_remove_coderproblem_true_coders_coder_i_33e18c_idx_and_more'), ('true_coders', '0078_coderproblem_contest_coderproblem_statistic'), ('true_coders', '0079_coderproblem_problem_key')]

    dependencies = [
        ('clist', '0169_alter_problem_index'),
        ('ranking', '0136_statistics_penalty_and_more'),
        ('true_coders', '0070_coder_n_subscribers'),
    ]

    operations = [
        migrations.CreateModel(
            name='ListGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('coder_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='groups', to='true_coders.coderlist')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='listvalue',
            name='new_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='true_coders.listgroup'),
        ),
        migrations.RunPython(
            code=set_new_group,
        ),
        migrations.RemoveConstraint(
            model_name='listvalue',
            name='unique_account',
        ),
        migrations.RemoveIndex(
            model_name='listvalue',
            name='true_coders_coder_l_1cff61_idx',
        ),
        migrations.RemoveField(
            model_name='listvalue',
            name='group_id',
        ),
        migrations.RenameField(
            model_name='listvalue',
            old_name='new_group',
            new_name='group',
        ),
        migrations.AddIndex(
            model_name='listvalue',
            index=models.Index(fields=['coder_list', 'group'], name='true_coders_coder_l_1cff61_idx'),
        ),
        migrations.AddConstraint(
            model_name='listvalue',
            constraint=models.UniqueConstraint(condition=models.Q(('account__isnull', False)), fields=('coder_list', 'account', 'group'), name='unique_account'),
        ),
        migrations.AlterField(
            model_name='listvalue',
            name='group',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='values', to='true_coders.listgroup'),
        ),
        migrations.AddField(
            model_name='listgroup',
            name='name',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='coderlist',
            name='with_names',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='coderproblem',
            name='upsolving',
            field=models.BooleanField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='coderproblem',
            name='submission_time',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddIndex(
            model_name='coderproblem',
            index=models.Index(fields=['coder', 'submission_time'], name='true_coders_coder_i_05932c_idx'),
        ),
        migrations.AddField(
            model_name='coderproblem',
            name='contest',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='clist.contest'),
        ),
        migrations.AddField(
            model_name='coderproblem',
            name='statistic',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='ranking.statistics'),
        ),
        migrations.AddField(
            model_name='coderproblem',
            name='problem_key',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
