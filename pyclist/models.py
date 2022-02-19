from django.db import models
from django.db.models.fields import Field
from django.db.models.lookups import LessThan
from django.utils.timezone import now

from utils.datetime import parse_duration


class DateDuringLookup(LessThan):

    def __init__(self, lhs, rhs):
        rhs = now() + parse_duration(rhs)
        super().__init__(lhs, rhs)


Field.register_lookup(DateDuringLookup, lookup_name='during')


class BaseModel(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class BaseManager(models.Manager):

    class Meta:
        abstract = True
