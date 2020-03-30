import re
import functools
import operator
from django.db.models import Q


def verify_regex(regex):
    try:
        re.compile(regex)
    except Exception:
        regex = re.sub(r'([\{\}\[\]\(\)\\\*\+\?])', r'\\\1', regex)
    return regex


def get_iregex_filter(regex, *fields):
    ret = Q()
    for r in regex.split():
        r = verify_regex(r)
        ret = ret & functools.reduce(operator.ior, (Q(**{f'{field}__iregex': r}) for field in fields))
    return ret
