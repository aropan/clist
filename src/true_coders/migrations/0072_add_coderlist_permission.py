# Generated by Django 5.1.4 on 2025-01-11 08:57

from django.db import migrations


class Migration(migrations.Migration):

    replaces = [('true_coders', '0072_alter_coderlist_options'), ('true_coders', '0073_alter_coderlist_options')]

    dependencies = [
        ('true_coders', '0071_edit_coder_list'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='coderlist',
            options={'permissions': (('manage_coderlist', 'Can manage coder lists'),)},
        ),
    ]
