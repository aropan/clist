from typing import Any, Optional

from django.apps import apps
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.fields import Field
from django.db.models.lookups import LessThan
from django.utils.timezone import now
from sql_util.utils import Exists

from logify.event_status import EventStatus
from utils.timetools import parse_duration


class DateDuringLookup(LessThan):

    def __init__(self, lhs, rhs):
        rhs = now() + parse_duration(rhs)
        super().__init__(lhs, rhs)


Field.register_lookup(DateDuringLookup, lookup_name='during')


class BaseModel(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    def fetched_field(self, field) -> Optional[Any]:
        fields = field.split('__')
        obj = self
        for field in fields:
            if field not in obj._state.fields_cache:
                return
            obj = getattr(obj, field)
        return obj

    class Meta:
        abstract = True

    @property
    def channel_group_name(self):
        return f'{self.__class__.__name__.upper()}__{self.pk}'


class BaseQuerySet(models.QuerySet):

    def annotate_favorite(self, instance):
        if isinstance(instance, (User, AnonymousUser)):
            coder = instance.coder if instance.is_authenticated else None
        else:
            coder = instance

        if not coder:
            return self.annotate(is_favorite=Value(False, output_field=models.BooleanField()))

        Activity = apps.get_model('favorites.Activity')
        content_type = ContentType.objects.get_for_model(self.model)
        qs = Activity.objects.filter(
            coder=coder,
            activity_type=Activity.Type.FAVORITE,
            content_type=content_type,
            object_id=OuterRef('pk'),
        )
        return self.annotate(is_favorite=Exists(qs))

    def annotate_note(self, instance):
        if isinstance(instance, (User, AnonymousUser)):
            coder = instance.coder if instance.is_authenticated else None
        else:
            coder = instance

        if not coder:
            return self.annotate(is_note=Value(False, output_field=models.BooleanField()))

        Note = apps.get_model('notes.Note')
        content_type = ContentType.objects.get_for_model(self.model)
        qs = Note.objects.filter(coder=coder, content_type=content_type, object_id=OuterRef('pk'))
        ret = self.annotate(is_note=Exists(qs))
        ret = ret.annotate(note_text=Subquery(qs.values('text')[:1]))
        return ret

    def annotate_active_executions(self):
        EventLog = apps.get_model('logify.EventLog')
        content_type = ContentType.objects.get_for_model(self.model)
        qs = EventLog.env_objects.filter(
            content_type=content_type,
            object_id=OuterRef('pk'),
            status=EventStatus.IN_PROGRESS,
        )
        return self.annotate(has_active_executions=Exists(qs))

    class Meta:
        abstract = True


class _BaseManager(models.Manager):

    class Meta:
        abstract = True


BaseManager = _BaseManager.from_queryset(BaseQuerySet)
