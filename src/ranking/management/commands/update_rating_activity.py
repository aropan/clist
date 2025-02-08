#!/usr/bin/env python3

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import F, Max, Q
from django.db.models.functions import Greatest
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from logify.models import EventStatus
from logify.utils import logging_event
from ranking.models import Account
from utils.attrdict import AttrDict
from utils.logger import suppress_db_logging_context
from utils.timetools import parse_datetime


class Command(BaseCommand):
    help = 'Update rating activity'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.update_rating_activity')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-bs', '--batch-size', type=int, help='batch size', default=1000)
        parser.add_argument('-n', '--limit', type=int, help='number of accounts')
        parser.add_argument('-s', '--order-by', type=str, help='order by field')
        parser.add_argument('--activity-filter', type=str, help='activity filter')
        parser.add_argument('--account-id', type=int, help='account id')
        parser.add_argument('--reset', action='store_true',  help='reset rating activity before update')
        parser.add_argument('--verbose', action='store_true', help='verbose output')

    def log_queryset(self, name, qs):
        total = qs.count()
        self.logger.info(f'{name} ({total}) = {qs}')

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.filter(has_rating_history=True)

        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)

        if args.order_by:
            resources = resources.order_by(args.order_by)

        if args.account_id:
            resources = resources.filter(account__id=args.account_id)

        self.log_queryset('resources', resources)

        resource_progress = tqdm(resources, total=resources.count(), desc='resources')
        for resource in resource_progress:
            resource_progress.set_description(f'resources ({resource})')
            with logging_event(
                name='update_rating_activity',
                related=resource,
                status=EventStatus.IN_PROGRESS,
            ) as event_log:
                if args.reset:
                    Account.objects.filter(resource=resource).update(last_rating_activity=None)
                n_updated = 0
                major_contests = resource.major_contests()
                rated_major_contests = major_contests.filter(is_rated=True)
                accounts = (
                    Account.objects
                    .filter(resource=resource)
                    .filter(Q(statistics__skip_in_stats__isnull=True) | Q(statistics__skip_in_stats=False))
                    .filter(statistics__contest__in=rated_major_contests)
                    .annotate(stat_rating_activity=Greatest('statistics__last_activity',
                                                            'statistics__contest__start_time'))
                    .values_list('pk')
                    .annotate(rating_activity=Max('stat_rating_activity'))
                    .filter(Q(last_rating_activity__isnull=False) | Q(rating_activity__isnull=False))
                    .filter(
                        Q(last_rating_activity__isnull=True) | Q(rating_activity__isnull=True) |
                        Q(last_rating_activity__lt=F('rating_activity'))
                    )
                )
                if args.activity_filter:
                    activity_from = parse_datetime(args.activity_filter)
                    accounts = accounts.filter(last_activity__gt=activity_from)
                if args.account_id:
                    accounts = accounts.filter(pk=args.account_id)
                update_accounts = [Account(pk=pk, last_rating_activity=rating_activity)
                                   for pk, rating_activity in accounts]

                with suppress_db_logging_context():
                    fields = ['last_rating_activity']
                    offsets = list(range(0, len(update_accounts), args.batch_size))
                    for offset in tqdm(offsets, desc=f'{resource.host} batching {fields}'):
                        batch = update_accounts[offset:offset + args.batch_size]
                        n_updated += Account.objects.bulk_update(batch, fields)

                message = (
                    f'n_contests = {rated_major_contests.count()}'
                    f', n_accounts = {len(accounts)}'
                    f', n_updated = {n_updated}'
                )
                self.logger.info(f'{resource.host}: {message}')
                event_log.update_message(message)
