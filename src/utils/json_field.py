from django.db.models import F as JSONF
from django.db.models import FloatField, IntegerField
from django.db.models.functions import Cast


def CastJSONF(field_name, field_type):
    return Cast(JSONF(field_name), field_type)


def IntegerJSONF(field_name):
    return CastJSONF(field_name, field_type=IntegerField())


def FloatJSONF(field_name):
    return CastJSONF(field_name, field_type=FloatField())
