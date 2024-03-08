import re
from datetime import datetime
from functools import partial

from django.db.models import Avg, Case, Count, F, FloatField, IntegerField, Max, Min, Q, Sum, Value, When
from django.db.models.fields.related import RelatedField
from django.db.models.functions import Cast
from django_pivot.histogram import get_column_values, histogram
from tailslide import Percentile

from clist.templatetags.extras import title_field
from utils.json_field import JSONF
from utils.logger import NullLogger
from utils.mathutils import get_divisors


def make_bins(src, dst, n_bins, logger=NullLogger(), field=None, step=None, qs=None):
    n_bins += 1
    force_ending = False
    if isinstance(src, str):
        if not dst:
            logger.warning(f'One of border is empty, field = {field}')
            return
        if (
            field and qs is not None and
            len(values := list(qs.distinct(field).values_list(field, flat=True)[:n_bins])) < n_bins
        ):
            bins = values
            force_ending = True
        else:
            st = ord(src[0]) + 1 if src else 32
            fn = ord(dst[0])
            bins = [src] + [chr(int(round(st + (fn - st) * i / (n_bins - 1)))) for i in range(n_bins)] + [dst]
    else:
        if step is not None:
            for divisor in get_divisors(step, reverse=True):
                n_src = src - src % divisor
                n_dst = dst + (divisor - dst % divisor) % divisor
                delta = (n_dst - n_src) / (n_bins - 1)
                if divisor <= delta:
                    src, dst = n_src, n_dst
                    n_bins = (n_dst - n_src) // divisor + 1
                    break
        bins = [src + (dst - src) * i / (n_bins - 1) for i in range(n_bins)]
    if isinstance(src, int):
        bins = [int(round(b)) for b in bins]
    elif isinstance(src, float):
        bins = [round(b, 2) for b in bins]
    bins = list(sorted(set(bins)))
    if isinstance(src, int) and len(bins) < n_bins:
        bins.append(bins[-1] + 1)
    elif len(bins) == 1 or force_ending:
        bins.append(bins[-1])
    return bins


def make_histogram(values, n_bins=None, bins=None, src=None, dst=None, deltas=None):
    if bins is None:
        if src is None:
            src = min(values)
        if dst is None:
            dst = max(values)
        bins = make_bins(src, dst, n_bins)
    idx = 0
    ret = [0] * (len(bins) - 1)
    if deltas is None:
        deltas = [1] * len(values)
    for x, delta in sorted(zip(values, deltas)):
        while idx + 1 < len(bins) and bins[idx + 1] <= x:
            idx += 1
        if idx == len(ret):
            if bins[idx] == x:
                idx -= 1
            else:
                break
        ret[idx] += delta
    return ret, bins


def make_beetween(column, value, start, end=None):
    if end is None:
        return When(Q(**{column + '__gte': start}), then=Value(value))
    return When(Q(**{column + '__gte': start, column + '__lt': end}), then=Value(value))


def make_chart(qs, field, groupby=None, logger=NullLogger(), n_bins=42, cast=None, step=None, aggregations=None,
               bins=None, norm_value=None):
    context = {'title': title_field(field) + (f' (slice by {groupby})' if groupby else '')}

    if cast == 'int':
        cast = IntegerField()
    elif cast == 'float':
        cast = FloatField()
    else:
        cast = None

    if '__' in field:
        related_fields = set()
        for f in qs.model._meta.related_objects:
            related_fields.add(f.name)
        for f in qs.model._meta.many_to_many:
            related_fields.add(f.name)
        for f in qs.model._meta.fields:
            if isinstance(f, RelatedField):
                related_fields.add(f.name)

        related_field = field.split('__')[0]
        if related_field in related_fields or '___' in field:
            logger.error(f'use of an invalid field = {field}')
            return
        cast = cast or IntegerField()
        qs = qs.annotate(value=Cast(JSONF(field), cast))
    else:
        if cast:
            qs = qs.annotate(value=Cast(F(field), cast))
        else:
            qs = qs.annotate(value=F(field))
    context['queryset'] = qs
    context['field'] = field

    qs = qs.filter(value__isnull=False)

    if not qs.exists():
        logger.warning(f'Empty histogram, field = {field}')
        return

    src = qs.earliest('value').value
    dst = qs.latest('value').value
    if isinstance(src, datetime):
        context['x_type'] = 'time'
        context['x_from'] = src.timestamp()
        context['x_to'] = dst.timestamp()
    elif type(src) in (int, float):
        context['x_from'] = src
        context['x_to'] = dst
    if groupby and not isinstance(src, str):
        context['type'] = 'line'

    slice_on = None
    if groupby == 'resource':
        slice_on = 'resource__host'
    elif groupby == 'country':
        slice_on = 'country'
    elif groupby:
        slice_on = groupby

    if slice_on:
        field_values = get_column_values(qs, slice_on, choices='minimum')
        fields = [str(f) for f, v in field_values]
        if context['type'] != 'line':
            n_bins = max(2 * n_bins // len(fields) + 1, 4)
        context['fields'] = fields
        context['slice'] = slice_on

    bins = bins or make_bins(src=src, dst=dst, n_bins=n_bins, logger=logger, field=field, step=step, qs=qs)
    context['bins'] = bins.copy()

    bins.pop(-1)
    context['data'] = histogram(qs, 'value', bins=bins, slice_on=slice_on, choices='minimum')

    for idx, row in enumerate(context['data']):
        if isinstance(src, datetime):
            st = re.findall('([0-9]+|.)', str(context['bins'][idx]))
            fn = re.findall('([0-9]+|.)', str(context['bins'][idx + 1]))
            title = ''
            n_diff = 0
            for lhs, rhs in zip(st, fn):
                title += lhs
                if lhs != rhs:
                    n_diff += 1
                    if n_diff == 2:
                        break
            row['title'] = title
        else:
            interval = ']' if idx + 1 == len(context['data']) else ')'
            row['title'] = f"[{context['bins'][idx]}..{context['bins'][idx + 1]}{interval}"
        if norm_value:
            interval = context['bins'][idx + 1] - context['bins'][idx]
            if interval:
                row['value'] *= norm_value / interval

    if aggregations:
        whens = [
            make_beetween('value', idx, bins[idx], bins[idx + 1] if idx + 1 < len(bins) else None)
            for idx in range(len(bins))
        ]
        qs = qs.annotate(idx=Case(*whens, output_field=IntegerField()))
        qs = qs.order_by('idx').values('idx')
        for field, aggregation in aggregations.items():
            if isinstance(aggregation, dict):
                op = {
                    'sum': Sum, 'avg': Avg, 'min': Min, 'max': Max, 'count': Count,
                    'percentile': partial(Percentile, percentile=aggregation['percentile']),
                }
                aggregate_func = op[aggregation['op']]
                aggregate_field = aggregate_func(field)
            else:
                aggregate_field = aggregation

            if slice_on:
                histogram_annotation = {
                    display_value: aggregate_func(Case(When(Q(**{slice_on: field_value}), then=F(field))))
                    for field_value, display_value in field_values
                }
            else:
                histogram_annotation = {field: aggregate_field}
            result = qs.annotate(**histogram_annotation)

            for record in result:
                idx = record.pop('idx')
                record = {k: v if v is not None else 0 for k, v in record.items()}
                context['data'][idx].update(record)

    return context
