# Generated by Django 4.2.10 on 2024-03-02 22:22

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clist', '0140_contest_clist_conte_resourc_22b78f_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='problem',
            name='skip_rating',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
