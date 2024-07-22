# Generated by Django 4.2.11 on 2024-06-09 11:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('clist', '0150_contest_is_promoted'), ('clist', '0151_alter_contest_is_promoted'), ('clist', '0152_promotion'), ('clist', '0153_promotion_name'), ('clist', '0154_alter_promotion_time_attribute'), ('clist', '0155_alter_contest_standings_kind'), ('clist', '0156_promotion_background'), ('clist', '0157_resource_skip_for_contests_chart')]

    dependencies = [
        ('clist', '0149_resource_n_accounts_to_update'),
    ]

    operations = [
        migrations.AddField(
            model_name='contest',
            name='is_promoted',
            field=models.BooleanField(blank=True, db_index=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name='contest',
            name='standings_kind',
            field=models.CharField(blank=True, choices=[('icpc', 'ICPC'), ('scoring', 'SCORING'), ('cf', 'CF')], db_index=True, max_length=10, null=True),
        ),
        migrations.CreateModel(
            name='Promotion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('timer_message', models.CharField(blank=True, max_length=200, null=True)),
                ('time_attribute', models.CharField(choices=[('start_time', 'Start Time'), ('end_time', 'End Time')], max_length=50)),
                ('enable', models.BooleanField(blank=True, default=True, null=True)),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='clist.contest')),
                ('name', models.CharField(max_length=50)),
                ('background', models.ImageField(blank=True, null=True, upload_to='promotions')),
            ],
            options={
                'unique_together': {('contest', 'time_attribute')},
            },
        ),
        migrations.AddField(
            model_name='resource',
            name='skip_for_contests_chart',
            field=models.BooleanField(default=False),
        ),
    ]
