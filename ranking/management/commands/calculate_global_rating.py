#!/usr/bin/env python3

from collections import defaultdict
from logging import getLogger

import humanize
import tqdm
from attrdict import AttrDict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from elo_mmr_py import Contest as RateContest
from elo_mmr_py import rate
from sql_util.utils import SubqueryCount

from clist.models import Contest, Resource
from ranking.models import Account, Statistics
from true_coders.models import Coder


class Command(BaseCommand):
    help = 'Calculate global rating'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.calculate_global_rating')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host names for calculate')

    def handle(self, *args, **options):
        self.logger.info(f'options = {options}')
        args = AttrDict(options)

        resource_filter = Q()
        if args.resources:
            for r in args.resources:
                resource_filter |= Q(host__iregex=r) | Q(short_host=r)
        resources = Resource.objects.filter(resource_filter)

        self.logger.info(f'resources = {[r.host for r in resources]}')

        contests = Contest.objects.filter(is_rated=True).filter(resource__in=resources)
        contests = contests.filter(is_rated=True)
        contests = contests.order_by('end_time')

        n_contests = contests.count()
        self.logger.info(f'number of contests = {n_contests}')

        def get_contestant_key(stat):
            if stat.n_coders == 1:
                return f'coder {stat.coder}'
            return f'account {stat.account_id}'

        n_total = 0
        with tqdm.tqdm(contests, desc='contests', total=n_contests) as pbar:
            statistics_keys = {}
            rate_contests = []
            for contest in pbar:
                statistics = contest.statistics_set
                statistics = statistics.filter(place_as_int__isnull=False).order_by('place_as_int')
                statistics = statistics.annotate(n_coders=SubqueryCount('account__coders'))
                statistics = statistics.filter(Q(addition__has_key='new_rating') | Q(addition__has_key='rating_change'))

                coder = Coder.objects.filter(pk=OuterRef('account__coders__pk')).values('pk')[:1]
                statistics = statistics.annotate(coder=Subquery(coder))

                divisions = {}
                n_contestants = 0
                n_coders = 0
                seen = set()
                statistics_pks = {}
                for stat in statistics:
                    division = stat.addition.get('division')
                    info = divisions.setdefault(division, {
                        'standings': [],
                        'prev_place': None,
                        'prev_rank': None,
                        'rank': 0,
                        'ties': defaultdict(int),
                    })
                    assert 'new_rating' in stat.addition or 'rating_change' in stat.addition

                    key = get_contestant_key(stat)
                    statistics_pks[key] = stat.pk
                    n_total += 1
                    n_contestants += 1
                    n_coders += key.startswith('coder')
                    if stat.place_as_int != info['prev_place']:
                        info['prev_place'] = stat.place_as_int
                        info['prev_rank'] = info['rank']
                    if key not in seen:
                        info['standings'].append([key, info['prev_rank'], info['prev_rank']])
                        seen.add(key)
                    else:
                        self.logger.warning(f'Duplicate key = {key} while contest = {contest}')
                    info['ties'][info['prev_rank']] += 1
                    info['rank'] += 1

                pbar.set_postfix(contest=contest.title,
                                 date=contest.end_time.date(),
                                 pk=str(contest.pk),
                                 n_coders=n_coders,
                                 n_contestants=n_contestants,
                                 n_total=n_total)

                for division, info in divisions.items():
                    info['standings'] = [[key, lo, lo + info['ties'][lo] - 1] for key, lo, _ in info['standings']]
                    standigns_data = {
                        'name': contest.title,
                        'time_seconds': int(contest.end_time.timestamp()),
                        'standings': info['standings'],
                    }
                    contest_index = len(rate_contests)
                    for key, *_ in info['standings']:
                        model, pk = key.split()
                        if model == 'coder':
                            statistics_keys[statistics_pks[key]] = (int(pk), contest_index)
                    rate_contests.append(RateContest(**standigns_data))
            self.logger.info('rating...')
            rate_result = rate(rate_contests)
            self.logger.info(f'elapsed time = {humanize.precisedelta(rate_result.secs_elapsed)}')

        accounts_players = {}
        coders_players = {}

        for key, player in rate_result.players.items():
            model, pk = key.split()
            pk = int(pk)
            if model == 'account':
                accounts_players[pk] = player
            else:
                coders_players[pk] = player

        with transaction.atomic():
            self.logger.info('coders clearing...')
            updates = Coder.objects.filter(global_rating__isnull=False).update(global_rating=None)
            self.logger.info(f'number of updates = {updates}')

            self.logger.info('account clearing...')
            updates = Account.objects.filter(global_rating__isnull=False).update(global_rating=None)
            self.logger.info(f'number of updates = {updates}')

            # self.logger.info('statistics clearing...')
            # statistics = Statistics.objects.filter(new_global_rating__isnull=False, contest__is_rated=True)
            # updates = statistics.update(new_global_rating=None, global_rating_change=None)
            # self.logger.info(updates)

            self.logger.info(f'{len(coders_players)} coders updating...')
            statistics_updates = {}
            coders = Coder.objects.filter(pk__in=set(coders_players)).in_bulk()
            for pk, coder in coders.items():
                player = coders_players[pk]
                global_rating = player.event_history[-1].rating_mu
                coder.global_rating = global_rating
                rating = None
                for idx, history in enumerate(player.event_history):
                    change = history.rating_mu - rating if idx else None
                    rating = history.rating_mu
                    statistics_updates[(pk, history.contest_index)] = (rating, change)
            batch_size = int(len(coders) ** 0.5 + 1)
            Coder.objects.bulk_update(coders.values(), ['global_rating'], batch_size=batch_size)
            self.logger.info('done')

            self.logger.info(f'{len(statistics_keys)} statistics updating...')
            statistics_pks = list(statistics_keys)
            batch_size = int(len(statistics_pks) ** 0.5 + 1)
            for offset in tqdm.trange(0, len(statistics_pks), batch_size, desc='updating...'):
                pks = statistics_pks[offset:offset + batch_size]
                statistics = Statistics.objects.filter(pk__in=set(pks)).in_bulk()
                for pk, stat in statistics.items():
                    statistic_key = statistics_keys[pk]
                    if statistic_key not in statistics_updates:
                        _, contest_index = statistic_key
                        self.logger.error(f'missing statistic_key = {statistic_key}, '
                                          f'contest = "{rate_contests[contest_index].name}"')
                        continue
                    rating, change = statistics_updates[statistic_key]
                    stat.new_global_rating = rating
                    stat.global_rating_change = change
                Statistics.objects.bulk_update(statistics.values(), ['new_global_rating', 'global_rating_change'])
            self.logger.info('done')

            # self.logger.info('accounts updating...')
            # accounts = Account.objects.filter(pk__in=set(accounts_players)).in_bulk()
            # for pk, account in accounts.items():
            #     player = accounts_players[pk]
            #     global_rating = player.event_history[-1].rating_mu
            #     account.global_rating = global_rating
            # Account.objects.bulk_update(accounts.values(), ['global_rating'])
