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
from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from clist.models import Contest, Resource
from pyclist.models import BaseManager, BaseModel
from ranking.models import Account
from tg.models import Chat as CoderChat
from true_coders.models import Coder, CoderList
from utils.strings import markdown_to_html, markdown_to_text


class TaskNotification(BaseModel):
    coder = models.ForeignKey(Coder, on_delete=models.CASCADE, null=True, blank=True)
    method = models.CharField(max_length=256, null=False)
    enable = models.BooleanField(default=True)

    @property
    def method_type(self):
        ret, *_ = self.method.split(':', 1)
        return ret

    def send(self, message=None, markdown=True, contest=None, **kwargs):
        if markdown and message:
            if self.method_type == django_settings.NOTIFICATION_CONF.WEBBROWSER:
                message = markdown_to_text(message)
            elif self.method_type == django_settings.NOTIFICATION_CONF.EMAIL:
                message = markdown_to_html(message)
        if contest is not None and self.last_contest != contest:
            Task.create_contest_notification(notification=self, contest=contest)
            self.last_contest = contest
            self.last_update = timezone.now()
            self.save(update_fields=['last_contest', 'last_update'])
        Task.objects.create(notification=self, message=message, **kwargs)

    @property
    def notification_key(self):
        return f'{self.coder_id}:{self.method}'

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
        return f'{self.method}@{self.coder}: {self.before} {self.period} Notification#{self.id}'

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


class EnabledSubscriptionManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().filter(enable=True)


class Subscription(TaskNotification):
    resource = models.ForeignKey(Resource, null=True, blank=True, default=None, on_delete=models.CASCADE)
    contest = models.ForeignKey(Contest, null=True, blank=True, default=None, on_delete=models.CASCADE)
    coders = models.ManyToManyField(Coder, blank=True, related_name='subscribers')
    accounts = models.ManyToManyField(Account, blank=True, related_name='subscribers')
    coder_list = models.ForeignKey(CoderList, null=True, blank=True, default=None, on_delete=models.CASCADE)
    coder_chat = models.ForeignKey(CoderChat, null=True, blank=True, default=None, on_delete=models.CASCADE)
    last_contest = models.ForeignKey(Contest, null=True, blank=True, default=None, on_delete=models.CASCADE,
                                     related_name='last_contest_subscriptions')
    last_update = models.DateTimeField(null=True, blank=True)
    with_first_accepted = models.BooleanField(default=False)
    top_n = models.IntegerField(null=True, blank=True)
    with_custom_names = models.BooleanField(default=False)

    tasks = GenericRelation(
        'Task',
        object_id_field='notification_object_id',
        content_type_field='notification_content_type',
        related_query_name='subscription',
    )

    objects = BaseManager()
    enabled = EnabledSubscriptionManager()

    class Meta:
        indexes = [
            models.Index(fields=['contest']),
            models.Index(fields=['resource']),
            models.Index(fields=['enable', 'resource', 'contest']),
            models.Index(fields=['resource', 'contest']),
            models.Index(fields=['resource', 'contest', 'with_first_accepted']),
            models.Index(fields=['resource', 'contest', 'top_n']),
        ]

    def __str__(self):
        ret = f'{self.method}@{self.coder}:'
        if self.resource_id:
            ret += f' {self.resource}'
        if self.contest_id:
            ret += f' {self.contest}'
        return f'{ret} Subscription#{self.id}'

    def form_data(self):
        ret = {}
        ret['id'] = self.id
        ret['method'] = {'id': self.method, 'text': self.method}
        if self.resource:
            ret['resource'] = {'id': self.resource.id, 'text': self.resource.host}
        if self.contest:
            ret['contest'] = {'id': self.contest.id, 'text': self.contest.title}
        accounts = ret.setdefault('accounts', [])
        for account in self.accounts.all():
            accounts.append({'id': account.id, 'text': account.display()})
        coders = ret.setdefault('coders', [])
        for coder in self.coders.all():
            coders.append({'id': coder.id, 'text': coder.detailed_name})
        if self.coder_list_id:
            ret['coder_list'] = {'id': self.coder_list.id, 'text': self.coder_list.name}
        if self.coder_chat_id:
            ret['coder_chat'] = {'id': self.coder_chat.id, 'text': self.coder_chat.title}
        ret['with_first_accepted'] = self.with_first_accepted
        ret['top_n'] = self.top_n
        return ret

    def is_empty(self):
        return not (self.accounts.exists() or self.coders.exists() or self.with_first_accepted or self.top_n)


@receiver(m2m_changed, sender=Subscription.accounts.through)
def update_account_n_subscribers_on_change(sender, instance, action, reverse, pk_set, **kwargs):
    when, action = action.split('_', 1)
    if when != 'post':
        return
    if action == 'add':
        delta = 1
    elif action == 'remove':
        delta = -1
    else:
        return

    if reverse:
        Account.objects.filter(pk=instance.pk).update(n_subscribers=models.F('n_subscribers') + delta)
    elif pk_set:
        Account.objects.filter(pk__in=pk_set).update(n_subscribers=models.F('n_subscribers') + delta)


@receiver(m2m_changed, sender=Subscription.coders.through)
def update_coder_n_subscribers_on_change(sender, instance, action, reverse, pk_set, **kwargs):
    when, action = action.split('_', 1)
    if when != 'post':
        return
    if action == 'add':
        delta = 1
    elif action == 'remove':
        delta = -1
    else:
        return

    if reverse:
        Coder.objects.filter(pk=instance.pk).update(n_subscribers=models.F('n_subscribers') + delta)
    elif pk_set:
        Coder.objects.filter(pk__in=pk_set).update(n_subscribers=models.F('n_subscribers') + delta)


@receiver(pre_delete, sender=Subscription)
def update_n_subscribers_on_delete(sender, instance, **kwargs):
    Account.objects.filter(subscribers=instance).update(n_subscribers=models.F('n_subscribers') - 1)
    Coder.objects.filter(subscribers=instance).update(n_subscribers=models.F('n_subscribers') - 1)


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

    @classmethod
    def create_contest_notification(cls, notification, contest, **kwargs):
        addition = kwargs.setdefault('addition', {})
        addition['contests'] = [contest.pk]
        Task.objects.create(notification=notification, **kwargs)

    def __str__(self):
        return 'Task#{0.id} {0.notification}'.format(self)


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
        if to.is_virtual or not accounts:
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
