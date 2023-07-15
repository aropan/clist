#!/usr/bin/env python3

from django.db.models import F, Q
from django.utils import timezone
from prettytable import PrettyTable
from sql_util.utils import SubqueryCount
from tqdm import tqdm

from scripts.common import pass_args

from clist.models import Resource
from ranking.models import Account


def main(host=None, full=False, skip_in_stats_fix=False, sortby='n_changes'):
    resources = Resource.objects.order_by('n_accounts')
    if host:
        resources = resources.filter(host__regex=host)
    total_resources = resources.count()

    fields = ['host', 'n_accounts', 'n_changes', 'percent', 'time']
    table = PrettyTable(field_names=fields, sortby=sortby)
    with tqdm(total=total_resources, desc='resources') as pbar_resource:
        for resource in resources:
            start_time = timezone.now()
            accounts = Account.objects.filter(resource=resource)
            if not full:
                accounts = accounts.filter(coders__isnull=False)
            total_accounts = accounts.count()

            if skip_in_stats_fix:
                for value in (False, True):
                    for a in tqdm(accounts, desc='fixing skip_in_stats'):
                        qs = a.statistics_set.filter(skip_in_stats=value, addition___no_update_n_contests=not value)
                        qs.update(skip_in_stats=not value)

            qs = accounts.annotate(count=SubqueryCount('statistics', filter=Q(skip_in_stats=False)))
            qs = qs.exclude(count=F('n_contests'))
            n_contests_diff = 0
            with tqdm(desc='updating n_contests') as pbar:
                for a in qs.iterator():
                    to_save = False
                    if a.count != a.n_contests:
                        n_contests_diff += 1
                        a.n_contests = a.count
                        to_save = True
                    if to_save:
                        a.save(update_fields=['n_contests'])
                    pbar.update()
                pbar.close()

            delta_time = timezone.now() - start_time
            pbar_resource.set_postfix(
                resource=resource.host,
                time=delta_time,
                total=accounts.count(),
                diff=n_contests_diff,
            )
            pbar_resource.update()
            table.add_row([
                resource.host,
                total_accounts,
                n_contests_diff,
                round(n_contests_diff / total_accounts, 3) if total_accounts else None,
                delta_time,
            ])

        pbar_resource.close()
    print(table)


def run(*args):
    pass_args(main, args)
