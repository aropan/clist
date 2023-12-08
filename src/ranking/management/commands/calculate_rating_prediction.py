#!/usr/bin/env python3

import hashlib
from collections import defaultdict
from logging import getLogger

import numpy as np
import tqdm
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Case, F, FloatField, Q, When
from django.utils.timezone import now
from numba import njit
from prettytable import PrettyTable
from sql_util.utils import SubqueryCount

from clist.models import Contest, Resource
from logify.models import EventLog, EventStatus
from ranking.models import Statistics
from utils.attrdict import AttrDict
from utils.json_field import FloatJSONF
from utils.logger import measure_time, suppress_db_logging_context


@njit
def E(delta: float):
    return 1 / (1 + 10 ** (-delta / 400))


@njit
def f(k: int):
    p = 5.0 / 7.0
    return 1 / (1 + 1 * (1 - p ** k) / (1 - p))


@njit
def binary_search(arr, val):
    left = 0
    right = len(arr)
    while left < right:
        middle = (left + right) // 2
        if arr[middle] < val:
            left = middle + 1
        else:
            right = middle
    return left


@njit
def enough_rating_for_rank_mean(ratings, rating, rank_mean):
    e_rank = 1
    for r in ratings:
        e_rank += E(r - rating)
    return e_rank < rank_mean


@njit
def calculate_expected_ratings(ranks, ratings, rating_limit=10000):
    n = len(ranks)
    expected_ratings = np.zeros((n, 2), dtype=np.float64)
    ranks_ratings = zip(ranks, ratings)

    rank_means = []
    for index, (rank, rating) in enumerate(ranks_ratings):
        e_rank = 0
        for r in ratings:
            e_rank += E(r - rating)
        e_rank += 0.5
        rank_mean = (rank * e_rank) ** 0.5
        rank_means.append((rank_mean, 0, index))
        rank_means.append((rank + 0.5, 1, index))

    rank_means.sort()
    window_rating = float(rating_limit)
    rank_rating = float(rating_limit)
    for rank_mean, field, index in rank_means:
        right = rank_rating

        while right - window_rating > 0 and enough_rating_for_rank_mean(ratings, right - window_rating, rank_mean):
            window_rating *= 2
        if not enough_rating_for_rank_mean(ratings, right - window_rating / 2, rank_mean):
            window_rating /= 2

        left = max(right - window_rating, 0)
        while right - left > 1e-3:
            middle = (left + right) / 2
            if enough_rating_for_rank_mean(ratings, middle, rank_mean):
                right = middle
            else:
                left = middle
        rank_rating = right
        expected_ratings[index][field] = rank_rating

    return expected_ratings


def calculate_rating_prediction(rankings):
    assert len(rankings) > 1

    rankings.sort(key=lambda r: r['old_rating'])
    ranks = np.array([r['rank'] for r in rankings])
    ratings = np.array([r['old_rating'] for r in rankings])
    expected_ratings = calculate_expected_ratings(ranks, ratings)
    for ranking, expected_rating in zip(rankings, expected_ratings):
        expected_rating = dict(zip(['rating', 'perf'], expected_rating))
        rating_change = f(ranking['n_contests']) * (expected_rating['rating'] - ranking['old_rating'])
        ranking['rating_perf'] = expected_rating['perf']
        ranking['rating_change'] = rating_change
    return True


def get_old_ratings(contest):
    resource = contest.resource
    accounts = Statistics.objects.filter(contest=contest, place_as_int__isnull=False).values('account_id')

    rating_field = resource.rating_prediction.get('rating_field', 'new_rating')
    latest_rating = Statistics.objects.filter(
        contest__start_time__lt=contest.start_time,
        contest__resource=resource,
        account__in=accounts,
    ).annotate(
        latest_rating=Case(
            When(**{f'addition__{rating_field}__isnull': False}, then=FloatJSONF(f'addition__{rating_field}')),
            When(rating_prediction__isnull=False, then=FloatJSONF(f'rating_prediction__{rating_field}')),
            output_field=FloatField(),
        ),
        member=F('account__key'),
    ).filter(
        account__rating__isnull=False,
        latest_rating__isnull=False,
    ).order_by(
        'account', '-contest__end_time'
    ).distinct('account').values('member', 'latest_rating')

    n_contests_filter = Q(contest__start_time__lt=contest.start_time, skip_in_stats=False)
    statistics = Statistics.objects.filter(
        contest=contest,
        account__in=accounts,
    ).filter(
        place_as_int__isnull=False,
    ).annotate(
        rank=F('place_as_int'),
        member=F('account__key'),
        n_contests=SubqueryCount('account__statistics', filter=n_contests_filter),
    )

    rankings = {}
    for statistic in statistics:
        ranking = {
            'rank': statistic.rank,
            'member': statistic.member,
            'n_contests': statistic.n_contests,
        }
        old_rating = statistic.get_old_rating(use_rating_prediction=False)
        if old_rating is not None:
            ranking['old_rating'] = old_rating
        rankings[ranking['member']] = ranking
    for account in latest_rating:
        rankings[account['member']].setdefault('old_rating', account['latest_rating'])
    rankings = list(rankings.values())
    for ranking in rankings:
        if ranking.get('old_rating') is None:
            ranking['old_rating'] = resource.rating_prediction['initial_rating']
        ranking['n_contests'] += 1

    rankings.sort(key=lambda r: r['rank'])
    return rankings


class Command(BaseCommand):
    help = 'Calculate rating prediction'
    VERSION = 'v1'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.calculate_rating_prediction')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host names to calculate')
        parser.add_argument('-c', '--contest', metavar='CONTEST', type=int, help='contest id')
        parser.add_argument('-cs', '--contests', metavar='CONTESTS', nargs='*', type=int, help='contest ids')
        parser.add_argument('-s', '--search', metavar='TITLE', help='contest title regex')
        parser.add_argument('-l', '--limit', metavar='LIMIT', type=int, help='limit contests')
        parser.add_argument('-f', '--force', action='store_true', help='force update')

    def handle(self, *_, **options):
        global args
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.all()
        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host__iregex=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)
            self.logger.info(f'resources = {[r.host for r in resources]}')
        else:
            resources = resources.filter(rating_prediction__isnull=False)

        contests = Contest.objects.filter(resource__in=resources, stage__isnull=True)
        contests = contests.filter(start_time__lt=now())
        if args.search:
            contests = contests.filter(title__regex=args.search)
        elif args.contest:
            contests = contests.filter(pk=args.contest)
        elif args.contests:
            contests = contests.filter(pk__in=args.contests)
        elif args.limit:
            contests = contests.order_by('-end_time')
            contests = contests[:args.limit]
        else:
            self.logger.warning('no contests specified')
            return

        contests = list(sorted(contests, key=lambda c: c.start_time))

        self.logger.info(f'contests = {[c.title for c in contests]}')
        skip_action = 'skip' if not args.force else 'ignore skipping'

        for contest in contests:
            resource = contest.resource

            if not contest.is_rating_prediction_timespan:
                self.logger.warning(f'{skip_action} contest with timespan, contest = {contest}')
                if not args.force:
                    continue

            event_log = EventLog.objects.create(name='calculate_rating_prediction',
                                                related=contest,
                                                status=EventStatus.IN_PROGRESS)

            with measure_time('get_old_ratings', logger=self.logger):
                rankings = get_old_ratings(contest)

            if len(rankings) < 2:
                self.logger.warning(f'skip contest with less than two rankings, contest = {contest}')
                event_log.update_status(EventStatus.SKIPPED, message='not enough rankings')
                continue

            values = tuple(sorted((r['rank'], r['member'], r['old_rating']) for r in rankings))
            values = (self.VERSION, values)
            rating_prediction_hash = hashlib.sha256(str(values).encode('utf8')).hexdigest()

            if contest.rating_prediction_hash == rating_prediction_hash:
                self.logger.warning(f'{skip_action} unchanged rating prediction hash, contest = {contest}')
                if not args.force:
                    event_log.update_status(EventStatus.SKIPPED, message='unchanged rating prediction hash')
                    continue

            with measure_time('calculate_rating_prediction', logger=self.logger):
                calculate_rating_prediction(rankings)

            for ranking in rankings:
                if 'rating_field' in resource.rating_prediction:
                    ndigits = resource.rating_prediction.get('rating_round')
                    rating = ranking['old_rating'] + ranking['rating_change']
                    ranking[resource.rating_prediction['rating_field']] = round(rating, ndigits)
                for field in 'rating_perf', 'rating_change':
                    ranking[field] = round(ranking[field])
                ranking['new_rating'] = round(ranking['old_rating']) + ranking['rating_change']

            rankings.sort(key=lambda r: r['rank'])
            fields = list(rankings[0].keys()) + ['change_diff']
            table = PrettyTable(field_names=fields)
            for ranking in rankings[:10]:
                stat = Statistics.objects.get(contest=contest, account__key=ranking['member'])
                prev_prediction = stat.rating_prediction
                if prev_prediction and 'rating_change' in prev_prediction and 'rating_change' in ranking:
                    ranking['change_diff'] = ranking.get('rating_change') - prev_prediction['rating_change']
                else:
                    ranking['change_diff'] = ''
                table.add_row([ranking[field] for field in fields])
            print(table)

            with transaction.atomic(), suppress_db_logging_context():
                rankings_dict = {ranking.pop('member'): ranking for ranking in rankings}
                statistics = Statistics.objects.filter(contest=contest, account__key__in=list(rankings_dict.keys()))
                statistics = statistics.select_related('account')
                has_fixed_field = False
                fields_types = defaultdict(set)
                for stat in tqdm.tqdm(statistics.iterator(),
                                      total=len(rankings_dict),
                                      desc='update statistics rating predictions'):
                    if 'rating_change' not in stat.addition:
                        has_fixed_field = True
                    stat.rating_prediction = rankings_dict[stat.account.key]
                    for k, v in stat.rating_prediction.items():
                        fields_types[k].add(type(v).__name__)
                    stat.save(update_fields=['rating_prediction'])
                fields_types = {k: list(v) for k, v in fields_types.items()}

                contest.rating_prediction_fields['types'] = fields_types
                contest.rating_prediction_hash = rating_prediction_hash
                contest.has_fixed_rating_prediction_field = has_fixed_field
                contest.rating_prediction_timing = now()
                contest.save(update_fields=['rating_prediction_hash',
                                            'rating_prediction_timing',
                                            'has_fixed_rating_prediction_field',
                                            'rating_prediction_fields'])
            event_log.update_status(EventStatus.COMPLETED)
