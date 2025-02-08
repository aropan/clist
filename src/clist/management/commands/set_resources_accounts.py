#!/usr/bin/env python
# -*- coding: utf-8 -*-

from collections import defaultdict
from logging import getLogger

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q, Sum
from django.utils import timezone
from prettytable import PrettyTable
from sql_util.utils import Exists, SubqueryCount
from tqdm import tqdm

from clist.models import Resource
from utils.attrdict import AttrDict
from utils.mathutils import is_close


class Command(BaseCommand):
    help = 'Set resources accounts'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.set_resources_accounts')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('--sortby', default='n_changes', help='sort by field')
        parser.add_argument('--with-coders', action='store_true', help='update only coders')
        parser.add_argument('--with-list-values', action='store_true', help='update only list values')
        parser.add_argument('--skip-fix', action='store_true', help='skip_in_stats fix')
        parser.add_argument('--remove-empty', action='store_true', help='remove empty accounts')
        parser.add_argument('--update-statistic-problem-stats', action='store_true',
                            help='update statistic problem stats')

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

        total_resources = resources.count()

        with tqdm(total=total_resources, desc='resources') as pbar_resource:
            table = None
            for resource in resources:
                start_time = timezone.now()

                if args.update_statistic_problem_stats:
                    only_fields = [
                        'id', 'account_id', 'resource_id', 'contest_id',
                        'addition', 'last_activity', 'skip_in_stats',
                        'solving', 'upsolving', 'total_solving',
                        'n_solved', 'n_upsolved', 'n_total_solved',
                        'n_first_ac',
                    ]
                    for statistic in resource.statistics_set.only(*only_fields):
                        statistic.update_stats()

                    for has_field, field in (
                        ('has_statistic_total_solving', 'total_solving'),
                        ('has_statistic_n_first_ac', 'n_first_ac'),
                        ('has_statistic_n_total_solved', 'n_total_solved'),
                    ):
                        if getattr(resource, has_field) is not None:
                            continue
                        if not resource.statistics_set.filter(**{f'{field}__gt': 0}).exists():
                            continue
                        setattr(resource, has_field, True)
                        resource.save(update_fields=[has_field])

                accounts = resource.account_set.all()
                if args.with_coders:
                    accounts = accounts.filter(coders__isnull=False)
                if args.with_list_values:
                    accounts = accounts.filter(listvalue__isnull=False)
                total_accounts = accounts.count()

                if args.skip_fix:
                    for value in (False, True):
                        for a in tqdm(accounts, desc='fixing skip_in_stats'):
                            qs = a.statistics_set.filter(skip_in_stats=value,
                                                         addition___no_update_n_contests=not value)
                            qs.update(skip_in_stats=not value)

                counters = defaultdict(int)

                def set_n_field(count_annotation, count_field):
                    qs = accounts.annotate(count=count_annotation).exclude(**{count_field: F('count')})
                    qs = qs.only('resource_id', count_field)
                    counter = 0
                    with tqdm(desc=f'updating {count_field}') as pbar:
                        for a in qs:
                            value = getattr(a, count_field)
                            if not is_close(value, a.count):
                                counter += 1
                                setattr(a, count_field, a.count)
                                a.save(update_fields=[count_field])
                            pbar.update()
                        pbar.close()
                    self.logger.info(f'updated {count_field} = {counter}')
                    counters[count_field] = counter

                def set_sum_field(sum_annotations, annotation_filter, name):
                    fields = list(sum_annotations.keys())
                    qs = accounts
                    qs = qs.filter(annotation_filter)
                    for field, annotation in sum_annotations.items():
                        qs = qs.annotate(**{f'_{field}': Sum(annotation)})
                    qs = qs.only('resource_id', *fields)
                    counter = 0
                    with tqdm(desc=f'updating {name}') as pbar:
                        for a in qs:
                            updated_fields = []
                            for field in fields:
                                value = getattr(a, f'_{field}') or 0
                                if not is_close(value, getattr(a, field)):
                                    setattr(a, field, value)
                                    updated_fields.append(field)
                            if updated_fields:
                                counter += 1
                                a.save(update_fields=updated_fields)
                            pbar.update()
                    self.logger.info(f'updated {name} = {counter}')
                    counters[name] = counter

                set_n_field(SubqueryCount('statistics', filter=Q(skip_in_stats=False)), 'n_contests')
                set_n_field(SubqueryCount('writer_set'), 'n_writers')
                set_n_field(SubqueryCount('subscribers'), 'n_subscribers')
                set_n_field(SubqueryCount('listvalue'), 'n_listvalues')

                if (
                    resource.has_statistic_total_solving or
                    resource.has_statistic_n_first_ac or
                    resource.has_statistic_n_total_solved
                ):
                    statistic_fields_annotation = {field: f'statistics__{field}'
                                                   for field in settings.ACCOUNT_STATISTIC_FIELDS}
                    set_sum_field(
                        statistic_fields_annotation,
                        annotation_filter=Q(statistics__contest__in=resource.major_contests()),
                        name='n_stats',
                    )

                if args.remove_empty:
                    qs = accounts.annotate(
                        has_coders=Exists('coders'),
                        has_statistics=Exists('statistics'),
                        has_writers=Exists('writer_set'),
                    ).filter(
                        has_coders=False,
                        has_statistics=False,
                        has_writers=False,
                    )
                    counters['n_removed'], _ = qs.delete()

                if table is None:
                    fields = ['host', 'time', 'n_accounts', 'n_changes']
                    fields += list(counters.keys())
                    table = PrettyTable(field_names=fields, sortby=args.sortby)

                n_changes = sum(counters.values())

                delta_time = timezone.now() - start_time
                pbar_resource.set_postfix(
                    resource=resource.host,
                    time=delta_time,
                    total=total_accounts,
                    n_changes=n_changes,
                )
                pbar_resource.update()
                table.add_row([
                    resource.host,
                    delta_time,
                    total_accounts,
                    n_changes,
                ] + list(counters.values()))

            pbar_resource.close()
            print(table)
