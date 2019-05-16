from pyclist.models import BaseModel
from django.db import models
from true_coders.models import Coder
from datetime import timedelta
from django.core.validators import MinValueValidator
from jsonfield import JSONField


class Notification(BaseModel):
    EMAIL = 'email'
    TELEGRAM = 'telegram'

    METHODS_CHOICES = (
        ('', '...'),
        (EMAIL, 'Email'),
        (TELEGRAM, 'Telegram'),
    )

    EVENT = 'event'
    HOUR = 'hour'
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'

    PERIOD_CHOICES = (
        ('', '...'),
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

    coder = models.ForeignKey(Coder, on_delete=models.CASCADE)
    method = models.CharField(max_length=256, null=False)
    before = models.IntegerField(null=False, validators=[MinValueValidator(0)])
    period = models.CharField(max_length=16, choices=PERIOD_CHOICES, null=False)
    last_time = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return '{0.method}@{0.coder}: {0.before} {0.period}'.format(self)


class Task(BaseModel):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE)
    subject = models.CharField(max_length=4096)
    message = models.TextField(null=False)
    addition = JSONField(default={}, blank=True)
    is_sent = models.BooleanField(default=False)

    class UnsentManager(models.Manager):
        def get_queryset(self):
            return super(Task.UnsentManager, self).get_queryset().filter(is_sent=False)

    objects = models.Manager()
    unsent = UnsentManager()

    def __str__(self):
        return '{0.notification}'.format(self)
