from datetime import datetime

from django.db.models import F, IntegerField
from django.db.models.fields.related import RelatedField
from django.db.models.functions import Cast
from django_pivot.histogram import get_column_values, histogram

from clist.templatetags.extras import title_field


def make_chart(qs, field, groupby=None, logger=None, n_bins=50):
    context = {'title': title_field(field) + (f' (slice by {groupby})' if groupby else '')}

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
            logger and logger.error(f'use of an invalid field = {field}')
            return
        qs = qs.annotate(value=Cast(F(field), IntegerField()))
    else:
        qs = qs.annotate(value=F(field))
    context['queryset'] = qs

    qs = qs.filter(value__isnull=False)

    slice_on = None
    if groupby == 'resource':
        slice_on = 'resource__host'
    elif groupby == 'country':
        slice_on = 'country'

    if slice_on:
        values = get_column_values(qs, slice_on, choices='minimum')
        fields = [f for f, v in values]
        n_bins = max(2 * n_bins // len(fields) + 1, 4)
        context['fields'] = fields
        context['slice'] = slice_on

    if not qs.exists():
        logger and logger.warning(f'Empty histogram, field = {field}')
        return

    src = qs.earliest('value').value
    dst = qs.latest('value').value
    if isinstance(src, str):
        if not dst:
            logger and logger.warning(f'One of border is empty, field = {field}')
            return
        st = ord(src[0]) + 1 if src else 32
        fn = ord(dst[0])
        bins = [src] + [chr(int(round(st + (fn - st) * i / (n_bins - 1)))) for i in range(n_bins)] + [dst]
        bins = list(sorted(set(bins)))
    else:
        bins = [src + (dst - src) * i / (n_bins - 1) for i in range(n_bins)]

    if isinstance(src, datetime):
        context['x_type'] = 'time'
    elif isinstance(src, int):
        bins = [int(round(b)) for b in bins]

    context['data'] = histogram(qs, 'value', bins=bins, slice_on=slice_on, choices='minimum')
    return context
