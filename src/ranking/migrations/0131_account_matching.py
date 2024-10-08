# Generated by Django 4.2.11 on 2024-06-09 21:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('ranking', '0131_accountmatching'), ('ranking', '0132_accountmatching_n_different_coders'), ('ranking', '0133_accountmatching_status'), ('ranking', '0134_alter_accountmatching_status'), ('ranking', '0135_alter_accountmatching_contest')]

    dependencies = [
        ('clist', '0151_resource_set_matched_coders_to_members'),
        ('clist', '0150_contest_promotion'),
        ('true_coders', '0069_listvalue_true_coders_coder_l_1cff61_idx'),
        ('ranking', '0130_review_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountMatching',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('name', models.CharField(max_length=400)),
                ('n_found_accounts', models.IntegerField(blank=True, default=None, null=True)),
                ('n_found_coders', models.IntegerField(blank=True, default=None, null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='ranking.account')),
                ('coder', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.CASCADE, to='true_coders.coder')),
                ('contest', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='account_matchings', to='clist.contest')),
                ('resource', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='clist.resource')),
                ('statistic', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='ranking.statistics')),
                ('n_different_coders', models.IntegerField(blank=True, default=None, null=True)),
                ('status', models.CharField(choices=[('new', 'New'), ('pending', 'Pending'), ('skip', 'Skip'), ('already', 'Already'), ('done', 'Done'), ('error', 'Error')], default='new', max_length=10)),
            ],
            options={
                'unique_together': {('name', 'statistic')},
            },
        ),
    ]
