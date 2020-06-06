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


def get_iregex_filter(regex, *fields, mapping=None):
    ret = Q()
    for r in regex.split():
        fs = fields
        suff = '__iregex'
        if ':' in r and mapping:
            k, v = r.split(':', 1)
            if k in mapping:
                fs = mapping[k].get('fields', [k])
                suff = mapping[k].get('suff', '')
                r = v
        r = verify_regex(r)
        ret = ret & functools.reduce(operator.ior, (Q(**{f'{field}{suff}': r}) for field in fs))
    return ret
