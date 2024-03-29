# Generated by Django 3.1.14 on 2022-01-10 01:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('true_coders', '0047_coder_is_virtual'),
        ('notification', '0021_auto_20220110_0109'),
    ]

    operations = [
        migrations.CreateModel(
            name='NotificationMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('modified', models.DateTimeField(auto_now=True, db_index=True)),
                ('message', models.TextField()),
                ('level', models.TextField(null=True)),
                ('is_read', models.BooleanField(default=False)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('to', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages_set', to='true_coders.coder')),
            ],
        ),
        migrations.DeleteModel(
            name='Message',
        ),
        migrations.AddIndex(
            model_name='notificationmessage',
            index=models.Index(fields=['to', 'is_read'], name='notificatio_to_id_f43ab7_idx'),
        ),
    ]
