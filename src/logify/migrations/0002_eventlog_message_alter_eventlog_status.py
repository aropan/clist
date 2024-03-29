# Generated by Django 4.2.3 on 2023-09-23 08:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('logify', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventlog',
            name='message',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='eventlog',
            name='status',
            field=models.CharField(choices=[('default', 'Default'), ('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed'), ('in_progress', 'In Progress'), ('cancelled', 'Cancelled'), ('on_hold', 'On Hold'), ('initiated', 'Initiated'), ('reviewed', 'Reviewed'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('archived', 'Archived')], db_index=True, default='default', max_length=20),
        ),
    ]
