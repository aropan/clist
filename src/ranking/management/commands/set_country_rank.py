#!/usr/bin/env python3

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q, Window
from django.db.models.functions import Rank
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from ranking.models import CountryAccount
from utils.attrdict import AttrDict
from utils.logger import suppress_db_logging_context
from utils.rating import get_last_activity_weight, get_n_contests_weight, get_weighted_rating
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Set country rank'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.set_country_rank')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('--rank-update-delay', help='time delay after rank last update time',
                            default='5 days')
        parser.add_argument('--contest-update-delay', help='time delay after rating last update time',
                            default='1 days')
        parser.add_argument('--without-delay', action='store_true', help='do not check delay')
        parser.add_argument('--verbose', action='store_true', help='verbose output')
        parser.add_argument('-f', '--force', action='store_true', help='force update')

    def log_queryset(self, name, qs):
        total = qs.count()
        self.logger.info(f'{name} ({total}) = {qs}')

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.available_for_update_objects.all()
        now = timezone.now()

        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)

        if not args.without_delay and not args.force:
            rank_update_delay = parse_duration(args.rank_update_delay)
            contest_update_delay = parse_duration(args.contest_update_delay)
            need_update = (
                Q(country_rank_update_time__isnull=True) |
                (
                    Q(rank_update_time__isnull=False)
                    & Q(country_rank_update_time__lt=F('rank_update_time'))
                    & (Q(rating_update_time__isnull=False) & Q(rank_update_time__gt=F('rating_update_time')))
                )
            )
            long_update = (
                Q(country_rank_update_time__isnull=True) |
                Q(country_rank_update_time__lt=now - rank_update_delay)
            )
            short_update = Q(rank_update_time__isnull=True) | Q(rank_update_time__lt=now - contest_update_delay)
            resources = resources.filter(need_update & (long_update | short_update))

        self.log_queryset('resources', resources)

        resource_rank = Window(expression=Rank(), order_by=F('rating').desc())

        for resource in tqdm(resources, total=len(resources), desc='resources'):
            event_log = EventLog.objects.create(name='set_country_rank',
                                                related=resource, status=EventStatus.IN_PROGRESS)
            with failed_on_exception(event_log):
                qs = resource.account_set.filter(country__isnull=False)
                qs = qs.values('country').annotate(count=Count('country'))
                country_accounts = []
                for country_stat in qs:
                    country_account = CountryAccount(
                        resource=resource,
                        country=country_stat['country'],
                        n_accounts=country_stat['count'],
                    )
                    country_accounts.append(country_account)
                with suppress_db_logging_context():
                    country_accounts = CountryAccount.objects.bulk_create(country_accounts,
                                                                          update_conflicts=True,
                                                                          unique_fields=['resource', 'country'],
                                                                          update_fields=['n_accounts'])
                    countries = {c.country for c in country_accounts}
                    country_accounts = CountryAccount.objects.filter(resource=resource, country__in=countries)
                    country_accounts = {c.country: c for c in country_accounts}
                    CountryAccount.objects.filter(resource=resource).exclude(country__in=country_accounts).delete()

                last_rated_contest = resource.contest_set.filter(is_rated=True).order_by('-end_time').first()
                if resource.has_country_rating and last_rated_contest:
                    qs = resource.account_set.filter(rating__isnull=False, country__isnull=False,
                                                     last_rating_activity__isnull=False)
                    qs = qs.values('country', 'rating', 'n_contests', 'last_rating_activity')
                    country_ratings = {}
                    for account_stat in qs:
                        weight = 1
                        weight *= get_n_contests_weight(account_stat['n_contests'])
                        weight *= get_last_activity_weight(account_stat['last_rating_activity'],
                                                           base=last_rated_contest.end_time)
                        country_ratings.setdefault(account_stat['country'], []).append((weight, account_stat['rating']))
                    country_accounts_update = []
                    for country, ratings in country_ratings.items():
                        raw_rating = get_weighted_rating(ratings, target=0.5, threshold=False)
                        rating = round(raw_rating) or None
                        country_account = CountryAccount(
                            pk=country_accounts[country].pk,
                            n_rating_accounts=len(ratings),
                            rating=rating,
                            raw_rating=raw_rating,
                        )
                        country_accounts_update.append(country_account)
                    with suppress_db_logging_context():
                        CountryAccount.objects.bulk_update(country_accounts_update, ['rating', 'n_rating_accounts',
                                                                                     'raw_rating'])

                    qs = resource.countryaccount_set.filter(rating__isnull=False)
                    qs = qs.annotate(rank=resource_rank).values('country', 'rank')
                    country_accounts_update = []
                    for country_account in qs:
                        country_account = CountryAccount(
                            pk=country_accounts[country_account['country']].pk,
                            resource_rank=country_account['rank'],
                        )
                        country_accounts_update.append(country_account)
                    with suppress_db_logging_context():
                        CountryAccount.objects.bulk_update(country_accounts_update, ['resource_rank'])
                else:
                    CountryAccount.objects.filter(resource=resource).update(rating=None, n_rating_accounts=0,
                                                                            raw_rating=None, resource_rank=None)

            resource.country_rank_update_time = now
            resource.save(update_fields=['country_rank_update_time'])
            event_log.update_status(EventStatus.COMPLETED)
