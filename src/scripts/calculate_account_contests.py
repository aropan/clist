#!/usr/bin/env python3


import fire
from django.db.models import F, Q
from django.utils import timezone
from sql_util.utils import SubqueryCount
from tqdm import tqdm

from clist.models import Resource
from ranking.models import Account


def main(host=None, full=False):
    resources = Resource.objects.order_by('n_accounts')
    if host:
        resources = resources.filter(host__regex=host)
    total = resources.count()

    with tqdm(total=total, desc='resources') as pbar_resource:
        for resource in resources:
            start_time = timezone.now()
            accounts = Account.objects.filter(resource=resource)
            if not full:
                accounts = accounts.filter(coders__isnull=False)

            qs = accounts.annotate(count=SubqueryCount('statistics', filter=Q(skip_in_stats=False)))
            qs = qs.exclude(count=F('n_contests'))
            n_contests_diff = 0
            with tqdm(desc='accounts') as pbar:
                for a in qs.iterator():
                    to_save = False
                    if a.count != a.n_contests:
                        n_contests_diff += 1
                        a.n_contests = a.count
                        to_save = True
                    if to_save:
                        a.save()
                    pbar.update()
                pbar.close()

            pbar_resource.set_postfix(
                resource=resource.host,
                time=timezone.now() - start_time,
                total=accounts.count(),
                diff=n_contests_diff,
            )
            pbar_resource.update()

        pbar_resource.close()


def run(*args):
    fire.Fire(main, args)
