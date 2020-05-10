#!/usr/bin/env python3


from django.db import transaction
from django.db.models import F, Count
from django.utils import timezone
from tqdm import tqdm

from clist.models import Resource


def run(*args):
    resources = Resource.objects.all()

    qs = resources.annotate(count=Count('contest'))
    qs = qs.exclude(n_contests=F('count'))
    total = qs.count()
    print(timezone.now(), total)
    with tqdm(total=total, desc='calculating contests') as pbar:
        with transaction.atomic():
            for r in qs.iterator():
                r.n_contests = r.count
                r.save()
                pbar.update()
    print(timezone.now())

    qs = resources.annotate(count=Count('account'))
    qs = qs.exclude(n_accounts=F('account'))
    total = qs.count()
    print(timezone.now(), total)
    with tqdm(total=total, desc='calculating accounts') as pbar:
        with transaction.atomic():
            for r in qs.iterator():
                r.n_accounts = r.count
                r.save()
                pbar.update()
    print(timezone.now())
