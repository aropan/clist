#!/usr/bin/env python3


import fire
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from sql_util.utils import SubqueryCount, SubqueryMax
from tqdm import tqdm

from ranking.models import Account


def main(host=None):
    accounts = Account.objects
    if host:
        accounts = accounts.filter(resource__host__regex=host)
    print(timezone.now(), accounts.count())

    filt = Q(addition___no_update_n_contests__isnull=True)

    qs = accounts.annotate(count=SubqueryCount('statistics', filter=filt))
    qs = qs.exclude(n_contests=F('count'))
    total = qs.count()
    print(timezone.now(), total)
    with tqdm(total=total) as pbar:
        with transaction.atomic():
            for a in qs.iterator():
                a.n_contests = a.count
                a.save()
                pbar.update()
    print(timezone.now())

    qs = accounts.annotate(last=SubqueryMax('statistics__contest__start_time', filter=filt))
    qs = qs.exclude(last_activity=F('last'))
    total = qs.count()
    print(timezone.now(), total)
    with tqdm(total=total) as pbar:
        with transaction.atomic():
            for a in qs.iterator():
                a.last_activity = a.last
                a.save()
                pbar.update()
    print(timezone.now())


def run(*args):
    fire.Fire(main, args)
