from django.db.models import F
from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields.json import KeyTextTransform


class KeyTextTransformFactory:

    def __init__(self, key_name):
        self.key_name = key_name

    def __call__(self, *args, **kwargs):
        return KeyTextTransform(self.key_name, *args, **kwargs)


class JSONF(F):

    def resolve_expression(self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False):
        rhs = super().resolve_expression(query, allow_joins, reuse, summarize, for_save)

        field_list = self.name.split(LOOKUP_SEP)
        for name in field_list[1:]:
            rhs = KeyTextTransformFactory(name)(rhs)
        return rhs
