import functools
import operator
import re

from django.db.models import Q
from sql_util.utils import Exists


def verify_regex(regex, logger=None):
    try:
        re.compile(regex)
    except Exception as e:
        if logger:
            logger.warning(f'Regex "{regex}" has error: {e}')
        regex = re.sub(r'([\{\}\[\]\(\)\\\*\+\?])', r'\\\1', regex)
    return regex


def get_iregex_filter(
    expression,
    *fields,
    mapping=None,
    logger=None,
    values=None,
    queryset=None,
    suffix='__iregex',
):
    ret = Q()
    n_exists = 0
    for dis in expression.split('||'):
        cond = Q()
        for con in dis.split('&&'):
            r = con.strip()
            fs = fields
            suff = suffix
            neg = False
            if ':' in r and mapping:
                k, v = r.split(':', 1)
                if k.startswith('!'):
                    k = k[1:].strip()
                    neg = not neg
                if k in mapping:
                    mapped = mapping[k]
                    try:
                        fs = mapped['fields']

                        r = mapped['func'](v) if 'func' in mapped else v

                        suff = mapped.get('suff', '')
                        if callable(suff):
                            suff = suff(r)

                        exists = mapped.get('exists')
                        if exists:
                            if isinstance(r, str) and 'regex' in fs[0]:
                                r = verify_regex(r, logger=logger)
                            n_exists += 1
                            field = f'exists{n_exists}'
                            queryset = queryset.annotate(**{field: Exists(exists, filter=Q(**{fs[0]: r}))})
                            fs = [field]
                            r = True
                    except Exception as e:
                        if logger:
                            logger.error(f'Field "{k}" has error: {e}')
                        continue
                    if values is not None:
                        values.setdefault(k, []).append(r)

            if isinstance(r, str) and 'regex' in suff:
                if r.startswith('!'):
                    neg = not neg
                    r = r[1:].strip()
                r = verify_regex(r, logger=logger)

            cs = [Q(**{f'{field}{suff}': r}) for field in fs]
            if neg:
                cond &= functools.reduce(operator.iand, (~c for c in cs))
            else:
                cond &= functools.reduce(operator.ior, cs)
        ret |= cond
    if queryset is not None:
        return ret, queryset
    return ret
