# Generated by Django 3.1.14 on 2022-12-26 13:34

import tqdm
from django.db import migrations, models


def set_variables(apps, schema_editor):
    Contest = apps.get_model('clist', 'Contest')
    qs = Contest.objects.select_related('timing').filter(timing__isnull=False)
    for c in tqdm.tqdm(qs.iterator(), total=qs.count()):
        c.statistic_timing = c.timing.statistic
        c.notification_timing = c.timing.notification
        c.save()


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0088_auto_20221226_1206'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='notification_timing',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='contest',
            name='statistic_timing',
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),

        migrations.RunPython(set_variables),
    ]
