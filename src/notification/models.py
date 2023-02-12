import re
import traceback
import uuid
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from clist.models import Contest
from pyclist.models import BaseModel
from ranking.models import Account
from true_coders.models import Coder


class TaskNotification(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    method = models.CharField(max_length=256, null=False)
    enable = models.BooleanField(default=True)

    @property
    def method_type(self):
        ret, *_ = self.method.split(':', 1)
        return ret

    class Meta:
        abstract = True


class Notification(TaskNotification):

    EVENT = 'event'
    HOUR = 'hour'
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'

    PERIOD_CHOICES = (
        (EVENT, 'Event'),
        (HOUR, 'Hour'),
        (DAY, 'Day'),
        (WEEK, 'Week'),
        (MONTH, 'Month'),
    )

    DELTAS = {
        EVENT: timedelta(minutes=1),
        HOUR: timedelta(hours=1),
        DAY: timedelta(days=1),
        WEEK: timedelta(weeks=1),
        MONTH: timedelta(days=31),
    }

    before = models.IntegerField(null=False, validators=[MinValueValidator(0), MaxValueValidator(1000000)])
    period = models.CharField(max_length=16, choices=PERIOD_CHOICES, null=False)
    with_updates = models.BooleanField(default=True)
    with_results = models.BooleanField(default=False)
    with_virtual = models.BooleanField(default=False)
    clear_on_delete = models.BooleanField(default=True)
    last_time = models.DateTimeField(null=True, blank=True)
    secret = models.CharField(max_length=50, blank=True, null=True)

    tasks = GenericRelation(
        'Task',
        object_id_field='notification_object_id',
        content_type_field='notification_content_type',
        related_query_name='periodical_notification',
    )

    def __str__(self):
        return '{0.method}@{0.coder}: {0.before} {0.period}'.format(self)

    def save(self, *args, **kwargs):
        if not self.id:
            self.last_time = timezone.now()
        if not self.secret:
            self.secret = User.objects.make_random_password(length=50)
        super().save(*args, **kwargs)

    def get_delta(self):
        return Notification.DELTAS[self.period]

    def clean(self):
        if (
            self.method == django_settings.NOTIFICATION_CONF.WEBBROWSER
            and self.period != Notification.EVENT
        ):
            raise ValidationError('WebBrowser method must have Event period.')


class Subscription(TaskNotification):
    contest = models.ForeignKey(Contest, db_index=True, on_delete=models.CASCADE)
    account = models.ForeignKey(Account, db_index=True, on_delete=models.CASCADE)

    tasks = GenericRelation(
        'Task',
        object_id_field='notification_object_id',
        content_type_field='notification_content_type',
        related_query_name='subscription',
    )

    class Meta:
        indexes = [models.Index(fields=['contest', 'account'])]
        unique_together = ('coder', 'method', 'contest', 'account')


class Task(BaseModel):
    notification_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    notification_object_id = models.PositiveIntegerField()
    notification = GenericForeignKey('notification_content_type', 'notification_object_id')

    subject = models.CharField(max_length=4096, null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    addition = models.JSONField(default=dict, blank=True)
    response = models.JSONField(default=dict, blank=True, null=True)
    is_sent = models.BooleanField(default=False)

    class ObjectsManager(models.Manager):
        def get_queryset(self):
            return super().get_queryset().prefetch_related('notification__coder')

    class UnsentManager(ObjectsManager):
        def get_queryset(self):
            return super().get_queryset().filter(is_sent=False)

    objects = ObjectsManager()
    unsent = UnsentManager()

    def __str__(self):
        return 'task of {0.notification}'.format(self)


@receiver(pre_delete, sender=Task)
def delete_task(sender, instance, **kwargs):
    notification = instance.periodical_notification.first()
    if (
        notification is not None
        and notification.clear_on_delete
        and notification.method_type == django_settings.NOTIFICATION_CONF.TELEGRAM
        and instance.response
    ):
        from tg.bot import Bot
        bot = Bot()
        try:
            bot.delete_message(instance.response['chat']['id'], instance.response['message_id'])
        except Exception:
            traceback.print_exc()


class Calendar(BaseModel):

    class EventDescription(models.IntegerChoices):
        URL = 1
        HOST = 2
        DURATION = 3

        @classmethod
        def extract(cls, event, description):
            if description == cls.URL:
                return f'Link: {event.actual_url}'
            if description == cls.HOST:
                return f'Host: {event.host}'
            if description == cls.DURATION:
                return f'Duration: {event.hr_duration}'

    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    name = models.CharField(max_length=64)
    category = models.CharField(max_length=256, null=True, blank=True)
    resources = ArrayField(models.PositiveIntegerField(), null=True, blank=True)
    descriptions = ArrayField(models.PositiveSmallIntegerField(choices=EventDescription.choices), null=True, blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)


class NotificationMessage(BaseModel):
    to = models.ForeignKey(Coder, on_delete=models.CASCADE, related_name='messages_set')
    text = models.TextField()
    level = models.TextField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    sender = models.ForeignKey(Coder, null=True, blank=True, on_delete=models.CASCADE, related_name='sender_set')

    class Meta:
        indexes = [
            models.Index(fields=['to', 'is_read']),
        ]
        verbose_name = 'Message'

    @staticmethod
    def link_accounts(to, accounts, message=None, sender=None):
        if to.is_virtual:
            return

        text = 'New accounts have been linked to you. Check your <a href="/coder/" class="alert-link">profile page</a>.'
        if message:
            text += ' ' + message
        text = f'<div>{text}</div>'

        for account in accounts:
            context = {
                'account': account,
                'resource': account.resource,
                'with_resource': True,
                'without_country': True,
                'with_account_default_url': True,
            }
            rendered_account = render_to_string('account_table_cell.html', context)
            rendered_account = re.sub(r'\s*\n+', r'\n', rendered_account)
            text += f'<div>{rendered_account}</div>'

        NotificationMessage.objects.create(to=to, text=text, sender=sender)
