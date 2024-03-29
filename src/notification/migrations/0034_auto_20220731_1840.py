# Generated by Django 3.1.14 on 2022-07-31 18:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('true_coders', '0050_auto_20220320_2231'),
        ('ranking', '0069_auto_20220728_2257'),
        ('notification', '0033_remove_task_notification'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='enable',
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('method', models.CharField(max_length=256)),
                ('enable', models.BooleanField(default=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='ranking.account')),
                ('coder', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='true_coders.coder')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
