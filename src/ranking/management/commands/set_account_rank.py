#!/usr/bin/env python3

from logging import getLogger
from pprint import pprint

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q, Window
from django.db.models.functions import Rank
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from ranking.models import Account
from utils.attrdict import AttrDict
from utils.datetime import parse_duration
from utils.logger import suppress_db_logging_context


class Command(BaseCommand):
    help = 'Set account rank'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.set_account_rank')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-bs', '--batch-size', type=int, help='batch size', default=1000)
        parser.add_argument('-n', '--limit', type=int, help='number of accounts')
        parser.add_argument('-td', '--time-delay', help='time delay after rating last update time', default='3 hours')
        parser.add_argument('--verbose', action='store_true', help='verbose output')

    def log_queryset(self, name, qs):
        total = qs.count()
        self.logger.info(f'{name} ({total}) = {qs}')

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.filter(has_rating_history=True)
        now = timezone.now()

        if args.time_delay:
            time_delay = parse_duration(args.time_delay)
            threshold_time = now - time_delay

            long_wait = Q(rank_update_time__isnull=True) | Q(rank_update_time__lt=threshold_time)
            need_update = (
                Q(rank_update_time__isnull=True) |
                (Q(rating_update_time__isnull=False) & Q(rank_update_time__lt=F('rating_update_time')))
            )
            resources = resources.filter(need_update & long_wait)

        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)

        self.log_queryset('resources', resources)

        resource_rank = Window(expression=Rank(), order_by=F('rating').desc())

        n_updated = 0
        for resource in tqdm(resources, total=len(resources), desc='resources'):
            event_log = EventLog.objects.create(name='set_account_rank',
                                                related=resource,
                                                status=EventStatus.IN_PROGRESS)
            field = 'resource_rank'
            with failed_on_exception(event_log):
                qs = Account.objects.filter(resource=resource, rating__isnull=False)
                n_rating_accounts = qs.count()
                qs = qs.annotate(_rank=resource_rank)
                qs = qs.exclude(**{field: F('_rank')})
                qs = qs.values('pk', '_rank', field)
                message = f'field = {field}, to update {qs.count()} of {n_rating_accounts} accounts'
                message += f', rating_update_time = {resource.rating_update_time}'
                message += f', rank_update_time = {resource.rank_update_time}'
                self.logger.info(f'resource = {resource}, {message}')
                event_log.update_message(message)

                with transaction.atomic():
                    if args.limit:
                        qs = qs[:args.limit]

                    if args.verbose:
                        pprint(qs)

                    update_values = [Account(id=a['pk'], **{field: a['_rank']}) for a in qs]

                    with suppress_db_logging_context():
                        offsets = list(range(0, len(update_values), args.batch_size))
                        for offset in tqdm(offsets, desc=f'{resource.host} batching {field}'):
                            update_values_batch = update_values[offset:offset + args.batch_size]
                            n_updated += Account.objects.bulk_update(update_values_batch, [field])
            event_log.update_status(EventStatus.COMPLETED, message=message)
            resource.rank_update_time = now
            resource.n_rating_accounts = n_rating_accounts
            resource.save(update_fields=['rank_update_time', 'n_rating_accounts'])

        self.logger.info('n_updated = %d', n_updated)
