#!/usr/bin/env python3

from collections import defaultdict
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import models
from django.db.models import Case, Count, F, Q, When, Window
from django.db.models.functions import Rank
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from clist.templatetags.extras import get_country_code, medal_as_n_medal_fields, place_as_n_place_field
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from ranking.models import CountryAccount
from utils.attrdict import AttrDict
from utils.json_field import CharJSONF
from utils.logger import suppress_db_logging_context
from utils.rating import get_last_activity_weight, get_n_contests_weight, get_weighted_rating
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Set country rank'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.set_country_fields')

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
            resources = Resource.get(args.resources, queryset=resources)

        if not args.without_delay and not args.force and not args.resources:
            rank_update_delay = parse_duration(args.rank_update_delay)
            contest_update_delay = parse_duration(args.contest_update_delay)
            need_update = (
                Q(country_rank_update_time__isnull=True) | (
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
            rating_update = need_update & (long_update | short_update)

            medal_update = Q(country_rank_update_time__isnull=True) | (
                Q(contest_update_time__isnull=False) &
                Q(country_rank_update_time__lt=F('contest_update_time') + parse_duration('3 days')) &
                Q(country_rank_update_time__lt=now - parse_duration('1 days'))
            )

            resources = resources.filter(rating_update | medal_update)

        self.log_queryset('resources', resources)

        resource_rank = Window(expression=Rank(), order_by=F('rating').desc())

        for resource in tqdm(resources, total=len(resources), desc='resources'):
            event_log = EventLog.objects.create(name='set_country_fields',
                                                related=resource, status=EventStatus.IN_PROGRESS)
            with failed_on_exception(event_log):
                qs = resource.account_set.filter(country__isnull=False, account_type=resource.default_account_type)
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

                def statistics_base_queryset():
                    ret = resource.statistics_set.annotate(country=Case(
                        When(addition__country__gt='', then=CharJSONF('addition__country')),
                        When(account__country__isnull=False, then=F('account__country')),
                        default=None,
                        output_field=models.CharField(),
                    ))
                    ret = ret.filter(skip_in_stats=False, contest__invisible=False)

                    # FIXME: remote duplicate statistics by team_id
                    ret = ret.filter(account__account_type=resource.default_account_type)

                    return ret

                def update_medal_fields():
                    qs = statistics_base_queryset()
                    qs = qs.filter(medal__isnull=False)
                    qs = qs.values('country', 'medal', 'place_as_int').annotate(count=Count('medal'))
                    for row in qs:
                        country_code = get_country_code(row['country'])
                        country_account = resource.countryaccount_set.filter(country=country_code).first()
                        if not country_account:
                            self.logger.warning(f'country account not found for {row["country"]}')
                            continue
                        updated_fields = []
                        for field in medal_as_n_medal_fields(medal=row['medal'], place=row['place_as_int']):
                            value = getattr(country_account, field) or 0
                            setattr(country_account, field, value + row['count'])
                            updated_fields.append(field)
                        if updated_fields:
                            country_account.save(update_fields=updated_fields)

                def update_n_place_fields():
                    qs = statistics_base_queryset()
                    qs = qs.filter(contest__stage__isnull=True)
                    qs = qs.filter(place_as_int__gte=1, place_as_int__lte=10, contest__end_time__lt=timezone.now())
                    qs = qs.values('country', 'place_as_int').annotate(count=Count('place_as_int'))
                    countries_data = {}
                    for row in qs:
                        country_code = get_country_code(row['country'])
                        if not country_code:
                            self.logger.warning(f'country code not found for {row["country"]}')
                            continue
                        country_data = countries_data.setdefault(country_code, defaultdict(int))
                        field = place_as_n_place_field(row['place_as_int'])
                        country_data[field] += row['count']
                    for country_code, country_data in countries_data.items():
                        country_account = resource.countryaccount_set.filter(country=country_code).first()
                        if not country_account:
                            self.logger.warning(f'country account not found for {country_code}')
                            continue
                        for field, count in country_data.items():
                            setattr(country_account, field, count)
                        update_fields = list(country_data.keys())
                        country_account.save(update_fields=update_fields)

                def update_rating_fields():
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

                resource.countryaccount_set.all().update(
                    n_win=None, n_gold=None, n_silver=None, n_bronze=None, n_medals=None, n_other_medals=None,
                    n_first_places=None, n_second_places=None, n_third_places=None, n_top_ten_places=None,
                )
                if resource.has_country_medal:
                    update_medal_fields()
                if resource.has_country_place:
                    update_n_place_fields()

                last_rated_contest = resource.major_contests().filter(is_rated=True).order_by('-end_time').first()
                if resource.has_country_rating and last_rated_contest:
                    update_rating_fields()
                else:
                    CountryAccount.objects.filter(resource=resource).update(rating=None, n_rating_accounts=0,
                                                                            raw_rating=None, resource_rank=None)

            resource.country_rank_update_time = now
            resource.save(update_fields=['country_rank_update_time'])
            event_log.update_status(EventStatus.COMPLETED)
