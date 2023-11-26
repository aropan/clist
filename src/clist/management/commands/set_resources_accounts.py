#!/usr/bin/env python
# -*- coding: utf-8 -*-

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone
from prettytable import PrettyTable
from sql_util.utils import SubqueryCount
from tqdm import tqdm

from clist.models import Resource
from ranking.models import Account
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Set resources accounts'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.set_resources_acconts')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('--sortby', default='n_changes', help='sort by field')
        parser.add_argument('--with-coders', action='store_true', help='update only coders')
        parser.add_argument('--skip-fix', action='store_true', help='skip_in_stats fix')
        parser.add_argument('--remove-empty', action='store_true', help='remove empty accounts')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            filt = Q()
            for r in args.resources:
                filt |= Q(host__iregex=r)
            resources = Resource.objects.filter(filt)
        else:
            resources = Resource.objects.all()
        self.logger.info(f'resources [{len(resources)}] = {[r.host for r in resources]}')

        def set_n_contests(resources):
            total_resources = resources.count()

            fields = ['host', 'n_accounts', 'n_changes', 'percent', 'time', 'n_removed']
            table = PrettyTable(field_names=fields, sortby=args.sortby)
            with tqdm(total=total_resources, desc='resources') as pbar_resource:
                for resource in resources:
                    start_time = timezone.now()
                    accounts = Account.objects.filter(resource=resource)
                    if args.with_coders:
                        accounts = accounts.filter(coders__isnull=False)
                    total_accounts = accounts.count()

                    if args.skip_fix:
                        for value in (False, True):
                            for a in tqdm(accounts, desc='fixing skip_in_stats'):
                                qs = a.statistics_set.filter(skip_in_stats=value,
                                                             addition___no_update_n_contests=not value)
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

                    n_removed = '-'
                    if args.remove_empty:
                        qs = accounts.filter(
                            coders__isnull=True,
                            statistics__isnull=True,
                            writer_set__isnull=True,
                        )
                        n_removed = qs.delete()

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
                        n_removed,
                    ])

                pbar_resource.close()
            print(table)

        set_n_contests(resources)
