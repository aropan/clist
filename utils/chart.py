from datetime import datetime

from django.db.models import F
from django_pivot.histogram import get_column_values, histogram


def make_chart(qs, field, groupby=None):
    context = {}
    qs = qs.annotate(value=F(field))
    qs = qs.filter(value__isnull=False)
    src = qs.earliest('value').value
    dst = qs.latest('value').value
    n_bins = 50

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

    bins = [src + (dst - src) * i / (n_bins - 1) for i in range(n_bins)]
    if isinstance(src, datetime):
        context['x_type'] = 'time'
    elif isinstance(src, int):
        bins = [int(round(b)) for b in bins]

    context['data'] = histogram(qs, 'value', bins=bins, slice_on=slice_on, choices='minimum')

    from pprint import pprint
    pprint(context['data'])

    return context
