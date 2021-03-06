# Generated by Django 3.1.7 on 2021-03-08 14:49

import django.db.models.deletion
from django.db import migrations, models
from tqdm import tqdm


def fill_resource(apps, schema_editor):
    Problem = apps.get_model('clist', 'Problem')
    qs = Problem.objects.all()
    for problem in tqdm(qs.select_related('contest__resource').iterator(), total=qs.count(), desc='problem resource'):
        problem.resource = problem.contest.resource
        problem.save()


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0063_auto_20210301_2201'),
    ]

    operations = [
        migrations.AddField(
            model_name='problem',
            name='resource',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='clist.resource'),
        ),
        migrations.AlterField(
            model_name='banner',
            name='data',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='contest',
            name='info',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='resource',
            name='info',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='resource',
            name='ratings',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(fill_resource)
    ]
