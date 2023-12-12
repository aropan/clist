#!/usr/bin/env python3

from django.db.models import Q
from django.db.models.signals import m2m_changed
from tqdm import tqdm

from ranking.models import Account, update_account_url


def run(host):
    qs = Account.objects.filter(Q(url__isnull=True) | Q(coders__isnull=False))
    if host:
        qs = qs.filter(resource__host__regex=host)
    total = qs.count()
    iterator = qs.select_related('resource').prefetch_related('coders').iterator()
    for a in tqdm(iterator, total=total):
        update_account_url(m2m_changed, a, action='post_save')
