from django.db.models import F as JSONF
from django.db.models import FloatField, IntegerField, JSONField
from django.db.models.functions import Cast


def CastJSONF(field_name, field_type):
    return Cast(JSONF(field_name), field_type)


def JsonJSONF(field_name):
    return CastJSONF(field_name, field_type=JSONField())


def IntegerJSONF(field_name):
    return CastJSONF(field_name, field_type=IntegerField())


def FloatJSONF(field_name):
    return CastJSONF(field_name, field_type=FloatField())
