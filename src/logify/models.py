import logging

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone
from rq import get_current_job

from logify.event_status import EventStatus
from pyclist.models import BaseManager, BaseModel
from utils.rq import is_job_id_active

SUPERSEDED_EVENT_ERROR = "Superseded by a newer execution"
logger = logging.getLogger(__name__)


def get_event_job_id(name, related):
    related_type = related._meta.label_lower.replace(".", "_")
    return f"event_{name}_{related_type}_{related.pk}"


class EventLogManager(BaseManager):
    def create(self, *args, **kwargs):
        kwargs.setdefault("environment", settings.ENVIRONMENT)
        related = kwargs.get("related")
        operation_job_id = None
        if related is not None:
            if related.pk is None:
                raise ValueError("EventLog requires a saved related object")
            operation_job_id = get_event_job_id(kwargs["name"], related)

        if not kwargs.get("job_id"):
            if current_job := get_current_job():
                kwargs["job_id"] = current_job.id
            else:
                if operation_job_id is None:
                    raise ValueError("EventLog requires a saved related object to generate job_id")
                kwargs["job_id"] = operation_job_id

        if operation_job_id is None:
            return super().create(*args, **kwargs)

        now = timezone.now()
        content_type = ContentType.objects.get_for_model(related)
        operation = models.Q(
            name=kwargs["name"],
            content_type=content_type,
            object_id=related.pk,
        )
        active_statuses = (EventStatus.NONE, EventStatus.IN_PROGRESS)
        previous_job_ids = (
            self
            .filter(operation, environment=kwargs["environment"], status__in=active_statuses)
            .exclude(job_id__in=("", operation_job_id, kwargs["job_id"]))
            .exclude(job_id__isnull=True)
            .values_list("job_id", flat=True)
            .distinct()
        )
        stale_job_ids = []
        for previous_job_id in previous_job_ids:
            try:
                active = is_job_id_active(previous_job_id)
            except Exception:
                logger.exception("Failed to check whether RQ job %s is active", previous_job_id)
                continue
            if not active:
                stale_job_ids.append(previous_job_id)

        previous_execution = models.Q(job_id__in=("", operation_job_id, *stale_job_ids)) | models.Q(job_id__isnull=True)
        with transaction.atomic():
            self.filter(
                operation,
                previous_execution,
                environment=kwargs["environment"],
                status__in=active_statuses,
            ).update(
                status=EventStatus.INTERRUPTED,
                error=SUPERSEDED_EVENT_ERROR,
                elapsed=now - models.F("created"),
                modified=now,
            )
            return super().create(*args, **kwargs)

    def get_queryset(self):
        return super().get_queryset().select_related("content_type").prefetch_related("related")


class EnvironmentEventLogManager(EventLogManager):
    def get_queryset(self):
        return super().get_queryset().filter(environment=settings.ENVIRONMENT)

    def interrupt_in_progress(self, job_id, error):
        if not job_id:
            return 0
        return self.filter(job_id=job_id, status=EventStatus.IN_PROGRESS).update(
            status=EventStatus.INTERRUPTED,
            error=error,
            elapsed=timezone.now() - models.F("created"),
        )

    def finish_active(self, job_id, status, error):
        if not job_id:
            return []
        event_logs = list(
            self.filter(
                job_id=job_id,
                status__in=(EventStatus.NONE, EventStatus.IN_PROGRESS),
                is_live_stream=True,
            )
        )
        for event_log in event_logs:
            event_log.update(status=status, message="", error=error)
        return event_logs


class EventLog(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    related = GenericForeignKey("content_type", "object_id")
    name = models.CharField(max_length=50, db_index=True)
    status = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.NONE, db_index=True)
    message = models.TextField(blank=True, null=True, default=None)
    error = models.TextField(blank=True, null=True, default=None)
    elapsed = models.DurationField(blank=True, null=True, default=None)
    environment = models.CharField(max_length=20, blank=True)
    job_id = models.CharField(max_length=512, blank=True, null=True)
    is_live_stream = models.BooleanField(blank=True, null=True)

    objects = EventLogManager()
    env_objects = EnvironmentEventLogManager()

    class Meta:
        indexes = (
            models.Index(
                fields=["job_id", "environment"],
                condition=models.Q(job_id__isnull=False),
                name="event_job_environment_idx",
            ),
        )
        permissions = (("view_all_live_updates", "Can view all live updates"),)

    def __str__(self):
        return f"{self.related} EventLog#{self.id}"

    def related_is(self, model):
        return self.content_type_id == ContentType.objects.get_for_model(model).pk

    def update(self, status=None, message=None, error=None):
        update_fields = ["elapsed"]
        if status is not None:
            self.status = status
            update_fields.append("status")
        if message is not None:
            self.message = message
            update_fields.append("message")
        if error is not None:
            self.error = error
            update_fields.append("error")
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
        return f"{self.table_name} PgStat#{self.id}"
