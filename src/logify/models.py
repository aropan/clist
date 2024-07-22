from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from pyclist.models import BaseManager, BaseModel


class EventStatus(models.TextChoices):
    DEFAULT = 'default', 'Default'
    PENDING = 'pending', 'Pending'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    IN_PROGRESS = 'in_progress', 'In Progress'
    CANCELLED = 'cancelled', 'Cancelled'
    ON_HOLD = 'on_hold', 'On Hold'
    INITIATED = 'initiated', 'Initiated'
    REVIEWED = 'reviewed', 'Reviewed'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
    ARCHIVED = 'archived', 'Archived'
    DELETED = 'deleted', 'Deleted'
    SKIPPED = 'skipped', 'Skipped'
    REVERTED = 'reverted', 'Reverted'
    EXCEPTION = 'exception', 'Exception'
    INTERRUPTED = 'interrupted', 'Interrupted'


class EventLogManager(BaseManager):
    def get_queryset(self):
        return super().get_queryset().select_related('content_type').prefetch_related('related')


class EventLog(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    related = GenericForeignKey('content_type', 'object_id')
    name = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.DEFAULT, db_index=True)
    message = models.TextField(blank=True, null=True)
    elapsed = models.DurationField(blank=True, null=True)
    environment = models.CharField(max_length=20, blank=True, null=True, default=None)

    objects = EventLogManager()

    def __str__(self):
        return f'{self.related} EventLog#{self.id}'

    def save(self, *args, **kwargs):
        if self.environment is None:
            self.environment = settings.ENVIRONMENT
        super().save(*args, **kwargs)

    def update_status(self, status, message=None):
        self.status = status
        if message is not None:
            self.message = message
        self.elapsed = timezone.now() - self.created
        self.save(update_fields=['status', 'message', 'modified', 'elapsed'])

    def update_message(self, message):
        self.message = message
        self.elapsed = timezone.now() - self.created
        self.save(update_fields=['message', 'modified', 'elapsed'])


class PgStatTuple(BaseModel):
    table_name = models.CharField(max_length=255, db_index=True, unique=True)
    app_name = models.CharField(max_length=255, blank=True, null=True)
    table_len = models.BigIntegerField()
    tuple_count = models.BigIntegerField()
    tuple_len = models.BigIntegerField()
    tuple_percent = models.FloatField()
    dead_tuple_count = models.BigIntegerField()
    dead_tuple_len = models.BigIntegerField()
    dead_tuple_percent = models.FloatField()
    free_space = models.BigIntegerField()
    free_percent = models.FloatField()

    def __str__(self):
        return f'{self.table_name} PgStatTuple#{self.id}'
