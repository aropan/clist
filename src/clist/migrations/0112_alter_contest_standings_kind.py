# Generated by Django 4.2.3 on 2023-09-02 00:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0111_alter_contest_standings_kind'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contest',
            name='standings_kind',
            field=models.CharField(blank=True, choices=[('icpc', 'ICPC'), ('scoring', 'SCORING')], db_index=True, max_length=10, null=True),
        ),
    ]
