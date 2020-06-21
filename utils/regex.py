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


def get_iregex_filter(expression, *fields, mapping=None):
    ret = Q()
    for dis in expression.split(' || '):
        cond = Q()
        for con in dis.split(' && '):
            r = con.strip()
            fs = fields
            suff = '__iregex'
            if ':' in r and mapping:
                k, v = r.split(':', 1)
                if k in mapping:
                    mapped = mapping[k]
                    fs = mapped['fields']
                    suff = mapped.get('suff', '')
                    try:
                        r = mapped['func'](v) if 'func' in mapped else v
                    except Exception:
                        continue
            if isinstance(r, str):
                r = verify_regex(r)
            cond &= functools.reduce(operator.ior, (Q(**{f'{field}{suff}': r}) for field in fs))
        ret |= cond
    return ret
