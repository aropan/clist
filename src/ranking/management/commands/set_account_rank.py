#!/usr/bin/env python3

from logging import getLogger
from pprint import pprint

from django.core.management.base import BaseCommand
from django.db.models import F, FloatField, Min, Q, Window
from django.db.models.functions import Cast, Rank
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from clist.templatetags.extras import get_item
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from ranking.models import Account
from utils.attrdict import AttrDict
from utils.json_field import FloatJSONF
from utils.logger import suppress_db_logging_context
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Set account rank'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.set_account_rank')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-bs', '--batch-size', type=int, help='batch size', default=1000)
        parser.add_argument('-n', '--limit', type=int, help='number of accounts')
        parser.add_argument('-s', '--order', help='order by')
        parser.add_argument('-q', '--search', help='search by')
        parser.add_argument('--rank-update-delay', help='time delay after rank last update time',
                            default='5 days')
        parser.add_argument('--rating-update-delay', help='time delay after rating last update time',
                            default='1 day')
        parser.add_argument('--without-delay', action='store_true', help='do not check delay')
        parser.add_argument('--verbose', action='store_true', help='verbose output')

    def log_queryset(self, name, qs):
        total = qs.count()
        self.logger.info(f'{name} ({total}) = {qs}')

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.available_for_update_objects.filter(has_rating_history=True)
        now = timezone.now()

        if not args.without_delay:
            rank_update_delay = parse_duration(args.rank_update_delay)
            rating_update_delay = parse_duration(args.rating_update_delay)
            need_update = (
                Q(rank_update_time__isnull=True) |
                (Q(rating_update_time__isnull=False) & Q(rank_update_time__lt=F('rating_update_time')))
            )
            long_update = Q(rank_update_time__isnull=True) | Q(rank_update_time__lt=now - rank_update_delay)
            short_update = Q(rating_update_time__isnull=True) | Q(rating_update_time__lt=now - rating_update_delay)
            resources = resources.filter(need_update & (long_update | short_update))

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
                                                related=resource, status=EventStatus.IN_PROGRESS)
            field = 'resource_rank'
            coloring_field = get_item(resource, 'info.ratings.chartjs.coloring_field')
            resource_update_fields = ['rank_update_time', 'n_rating_accounts']
            with failed_on_exception(event_log):
                base_qs = Account.objects.filter(resource=resource, rating__isnull=False)
                n_rating_accounts = base_qs.count()
                base_qs = base_qs.annotate(_rank=resource_rank)
                exclude = {field: F('_rank')}
                fields = ['pk', '_rank', field]
                with_rank_percentile = coloring_field == 'rank_percentile'
                if with_rank_percentile:
                    base_qs = base_qs.annotate(
                        _percentile=Cast((F('_rank') - 1), FloatField()) / (n_rating_accounts - 1))
                    exclude.update({'_percentile': FloatJSONF('info__rank_percentile'),
                                    'info__rank_percentile__isnull': False})
                    fields.extend(['_percentile', 'info'])
                qs = base_qs
                qs = qs.exclude(**exclude)
                qs = qs.values(*fields)
                message = f'field = {field}, to update {qs.count()} of {n_rating_accounts} accounts'
                message += f', rating_update_time = {resource.rating_update_time}'
                message += f', rank_update_time = {resource.rank_update_time}'
                self.logger.info(f'resource = {resource}, {message}')
                event_log.update_message(message)

                if args.search:
                    qs = qs.filter(Q(key=args.search) | Q(name=args.search))
                if args.order:
                    qs = qs.order_by(args.order)
                if args.limit:
                    qs = qs[:args.limit]

                if args.verbose:
                    pprint(qs)

                update_values = []
                for data in qs:
                    values = {'id': data['pk'], field: data['_rank']}
                    if with_rank_percentile:
                        values['info'] = data['info']
                        values['info']['rank_percentile'] = data['_percentile']
                    update_values.append(Account(**values))
                update_fields = [field]
                if with_rank_percentile:
                    update_fields.extend(['info'])

                with suppress_db_logging_context():
                    offsets = list(range(0, len(update_values), args.batch_size))
                    for offset in tqdm(offsets, desc=f'{resource.host} batching {field}'):
                        update_values_batch = update_values[offset:offset + args.batch_size]
                        n_updated += Account.objects.bulk_update(update_values_batch, update_fields)

                if coloring_field and resource.ratings:
                    updated_rating = False
                    for rating in resource.ratings:
                        high = rating['high']
                        field = f'info__{coloring_field}'
                        rating_value = base_qs.filter(**{f'{field}__lt': high}).aggregate(_val=Min('rating'))['_val']
                        if rating.get('min_rating') != rating_value:
                            rating['min_rating'] = rating_value
                            updated_rating = True
                    if updated_rating:
                        resource_update_fields.append('ratings')

            resource.rank_update_time = now
            resource.n_rating_accounts = n_rating_accounts
            resource.save(update_fields=resource_update_fields)
            event_log.update_status(EventStatus.COMPLETED, message=message)

        self.logger.info('n_updated = %d', n_updated)
