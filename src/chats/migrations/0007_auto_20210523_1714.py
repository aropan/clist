# Generated by Django 3.1.8 on 2021-05-23 17:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chats', '0006_chatlog_coder'),
    ]

    operations = [
        migrations.AddField(
            model_name='chat',
            name='slug',
            field=models.TextField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name='chat',
            name='chat_type',
            field=models.CharField(choices=[('ROOM', 'Room'), ('PRIV', 'Private')], db_index=True, default='ROOM', max_length=4),
        ),
        migrations.AddIndex(
            model_name='chat',
            index=models.Index(fields=['chat_type'], name='chats_chat_chat_ty_f1a920_idx'),
        ),
        migrations.AddIndex(
            model_name='chat',
            index=models.Index(fields=['slug'], name='chats_chat_slug_d69050_idx'),
        ),
        migrations.AddIndex(
            model_name='chat',
            index=models.Index(fields=['chat_type', 'slug'], name='chats_chat_chat_ty_dadff9_idx'),
        ),
    ]
