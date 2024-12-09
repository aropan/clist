from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from pyclist.models import BaseManager, BaseModel


class EventStatus(models.TextChoices):
    NONE = 'none', 'None'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    IN_PROGRESS = 'in_progress', 'In Progress'
    CANCELLED = 'cancelled', 'Cancelled'
    SKIPPED = 'skipped', 'Skipped'
    INTERRUPTED = 'interrupted', 'Interrupted'
    WARNING = 'warning', 'Warning'


class EventLogManager(BaseManager):
    def create(self, *args, **kwargs):
        kwargs.setdefault('environment', settings.ENVIRONMENT)
        return super().create(*args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().select_related('content_type').prefetch_related('related')


class EventLog(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    related = GenericForeignKey('content_type', 'object_id')
    name = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.NONE, db_index=True)
    message = models.TextField(blank=True, null=True, default=None)
    error = models.TextField(blank=True, null=True, default=None)
    elapsed = models.DurationField(blank=True, null=True, default=None)
    environment = models.CharField(max_length=20, blank=True)

    objects = EventLogManager()

    def __str__(self):
        return f'{self.related} EventLog#{self.id}'

    def update(self, status=None, message=None, error=None):
        update_fields = ['modified', 'elapsed']
        if status is not None:
            self.status = status
            update_fields.append('status')
        if message is not None:
            self.message = message
            update_fields.append('message')
        if error is not None:
            self.error = error
            update_fields.append('error')
        self.elapsed = timezone.now() - self.created
        self.save(update_fields=update_fields)

    def update_status(self, status, message=None):
        self.update(status=status, message=message)

    def update_message(self, message):
        self.update(message=message)

    def update_error(self, error, status=EventStatus.FAILED):
        self.update(status=status, error=error)


class PgStat(BaseModel):
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

    last_vacuum = models.DateTimeField(blank=True, null=True)
    last_autovacuum = models.DateTimeField(blank=True, null=True)
    last_analyze = models.DateTimeField(blank=True, null=True)
    last_autoanalyze = models.DateTimeField(blank=True, null=True)

    table_size = models.BigIntegerField(blank=True, null=True)
    pretty_table_size = models.CharField(max_length=20, blank=True, null=True)
    initial_table_size = models.BigIntegerField(blank=True, null=True)
    diff_size = models.BigIntegerField(blank=True, null=True)
    pretty_diff_size = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f'{self.table_name} PgStat#{self.id}'
