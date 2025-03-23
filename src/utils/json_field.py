from django.db.models import F as JSONF
from django.db.models import FloatField, IntegerField, JSONField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast


def CastJSONF(field_name, field_type):
    return Cast(JSONF(field_name), field_type)


def JsonJSONF(field_name):
    return CastJSONF(field_name, field_type=JSONField())


def IntegerJSONF(field_name):
    return CastJSONF(field_name, field_type=IntegerField())


def FloatJSONF(field_name):
    return CastJSONF(field_name, field_type=FloatField())


def CharJSONF(field_name):
    if isinstance(field_name, str):
        field_name = field_name.split('__', 1)[::-1]
    return KeyTextTransform(*field_name)
