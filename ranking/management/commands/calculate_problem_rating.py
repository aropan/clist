#!/usr/bin/env python3

import hashlib
from collections import OrderedDict, defaultdict
from logging import getLogger
from pprint import pprint  # noqa

import tqdm
from attrdict import AttrDict
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.timezone import now

from clist.models import Contest, Resource
from clist.templatetags.extras import get_problem_key, get_problem_short, is_solved
from clist.views import update_problems
from utils.json_field import JSONF


def get_rating(wratings, target, threshold=0.95, cache=None):
    left = 0
    right = 5000

    for _ in range(14):
        middle = (left + right) / 2

        if cache is not None and middle in cache:
            e_total, weight_sum, positive_prob, negative_prob = cache[middle]
        else:
            e_total = 0
            weight_sum = 0
            positive_prob = 1
            negative_prob = 1
            for weight, rating in wratings:
                exp = (middle - rating) / 400
                e = 1 / (1 + 10 ** exp)
                weight_sum += weight
                e_total += weight * e
                positive_prob *= e
                negative_prob *= 1 - e
            if cache is not None:
                cache[middle] = e_total, weight_sum, positive_prob, negative_prob

        """
        Chmel_Tolstiy proposed for special case:
        * the maximum rating, in which everything will be solved with a probability of >= X%
        * the minimum rating of the problem, in which no one will solve with a probability of >= X%
        """
        if positive_prob > threshold:
            left = middle
        elif negative_prob > threshold:
            right = middle
        elif e_total < target:
            right = middle
        else:
            left = middle
    rating = (left + right) / 2
    return rating


class Command(BaseCommand):
    help = 'Calculate problem rating'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.calculate_problem_rating')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host names to calculate')
        parser.add_argument('-c', '--contest', metavar='CONTEST', type=int, help='contest id')
        parser.add_argument('-s', '--search', metavar='TITLE', nargs='*', help='contest title regex')
        parser.add_argument('-l', '--limit', metavar='LIMIT', type=int, help='number of contests limit')
        parser.add_argument('-f', '--force', action='store_true', help='force update')
        parser.add_argument('-n', '--dryrun', action='store_true', help='do not update')
        parser.add_argument('-o', '--onlynew', action='store_true', help='update new only')

    def handle(self, *args, **options):
        self.logger.info(f'options = {options}')
        args = AttrDict(options)

        resources = Resource.objects.all()
        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host__iregex=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)
            self.logger.info(f'resources = {[r.host for r in resources]}')

        contests = Contest.objects.filter(resource__in=resources, stage__isnull=True)
        if args.search:
            contests = contests.filter(title__regex=args.search)
        if args.contest:
            contests = contests.filter(pk=args.contest)
        contests = contests.order_by('-end_time')
        contests = contests.filter(end_time__lt=now())
        contests = contests.exclude(problem_set=None)
        contests = contests.select_related('resource')
        if args.onlynew:
            contests = contests.filter(info___problems_ratings_hash__isnull=True)
        if args.limit:
            contests = contests[:args.limit]

        def get_statistics(contest):
            statistics = contest.statistics_set.all()
            statistics = statistics.select_related('account')
            statistics = statistics.filter(place_as_int__isnull=False)
            statistics = statistics.order_by('place_as_int')
            return statistics

        def get_info_key(statistic):
            division = statistic.addition.get('division')
            return (statistic.contest_id, division)

        def is_skip(statistic):
            return stat.account.info.get('is_team') or stat.addition.get('team_id') or stat.addition.get('_members')

        ratings = []
        for contest in tqdm.tqdm(contests, total=contests.count(), desc='contests'):
            resource = contest.resource

            if not contest.is_major_kind():
                self.logger.warning(f'skip not major kind contest = {contest}')
                continue

            statistics = get_statistics(contest)

            self.logger.info(f'number of statistics = {statistics.count()}')

            problems_contests = OrderedDict()
            problems_contests[contest] = statistics
            for problem in contest.problem_set.all():
                for problem_contest in problem.contests.all():
                    if problem_contest not in problems_contests:
                        problems_contests[problem_contest] = get_statistics(problem_contest)

            ratings = []
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='ratings'):
                    if is_skip(stat):
                        continue
                    problems = current_contest.info['problems']
                    if 'division' in problems:
                        problems = problems['division'][stat.addition.get('division')]

                    row = []
                    for problem in problems:
                        key = get_problem_key(problem)
                        short = get_problem_short(problem)
                        problem_result = stat.addition.get('problems', {}).get(short, {})
                        row.append((key, is_solved(problem_result)))
                    row.sort()
                    ratings.append(tuple([get_info_key(stat), stat.account_id] + row))
            if not ratings:
                self.logger.warning(f'skip empty contest = {contest}')
                continue

            ratings = tuple(sorted(ratings))
            problems_ratings_hash = hashlib.sha256(str(ratings).encode('utf8')).hexdigest()
            empty_problem_rating = False
            for problem in contest.problem_set.all():
                if problem.rating is None:
                    empty_problem_rating = True
                    break
            if (
                not empty_problem_rating and
                not args.force and
                contest.info.get('_problems_ratings_hash') == problems_ratings_hash
            ):
                self.logger.warning(f'skip unchanged hash contest = {contest}')
                continue

            contests_divisions_data = {}
            old_ratings = {}
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='old_ratings'):
                    if is_skip(stat):
                        continue
                    old_rating = stat.get_old_rating()
                    if old_rating is None:
                        old_rating = (
                            stat.account.statistics_set
                            .filter(contest__end_time__lt=current_contest.end_time)
                            .filter(Q(addition__new_rating__isnull=False) | Q(addition__old_rating__isnull=False))
                            .filter(contest__stage__isnull=True)
                            .filter(contest__kind=current_contest.kind)
                            .order_by('-contest__end_time')
                            .annotate(rating=JSONF('addition__new_rating'))
                            .values_list('rating', flat=True)
                            .first()
                        )
                    if old_rating is None:
                        old_rating = resource.avg_rating

                    old_ratings[stat.pk] = old_rating

                    info = contests_divisions_data.setdefault(get_info_key(stat), {
                        'wratings': [],
                        'places': defaultdict(int),
                        'orders': {},
                    })
                    info['wratings'].append((1.0, old_rating))
                    info['places'][stat.place_as_int] += 1

            for info in contests_divisions_data.values():
                rank = 0
                for place, size in sorted(info['places'].items()):
                    info['orders'][place] = rank + size / 2
                    rank += size

            problems_infos = dict()
            caches = dict()
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='perfomances'):
                    if is_skip(stat):
                        continue
                    info = contests_divisions_data[get_info_key(stat)]
                    cache = caches.setdefault(get_info_key(stat), {})
                    perfomance = get_rating(info['wratings'], info['orders'][stat.place_as_int], cache=cache)
                    rating = (perfomance + old_ratings[stat.pk]) / 2

                    problems = current_contest.info['problems']
                    if 'division' in problems:
                        problems = problems['division'][stat.addition.get('division')]

                    has_rating = 'new_rating' in stat.addition or 'rating_change' in stat.addition
                    weight = 1.0 if has_rating else 0.1

                    for problem in problems:
                        key = get_problem_key(problem)
                        if contest.pk != current_contest.pk and key not in problems_infos:
                            continue
                        short = get_problem_short(problem)
                        problem_info = problems_infos.setdefault(key, {'wratings': [], 'solved': 0})
                        problem_info['wratings'].append((weight, rating))
                        problem_result = stat.addition.get('problems', {}).get(short, {})
                        if is_solved(problem_result):
                            solved = 1
                        elif problem_result.get('partial') and problem.get('full_score'):
                            solved = float(problem_result.get('result', 0)) / problem.get('full_score')
                        else:
                            solved = 0
                        problem_info['solved'] += weight * solved

            problems_ratings = {}
            for problem_key, problem_info in problems_infos.items():
                rating = get_rating(problem_info['wratings'], problem_info['solved'])
                problems_ratings[problem_key] = round(rating)

            if not args.dryrun:
                problems = contest.info['problems']
                if 'division' in problems:
                    list_problems = []
                    for d in problems['division'].values():
                        list_problems.extend(d)
                else:
                    list_problems = problems
                for problem in list_problems:
                    key = get_problem_key(problem)
                    problem['rating'] = problems_ratings[key]
                update_problems(contest, problems, force=True)
                contest.info['_problems_ratings_hash'] = problems_ratings_hash
                contest.save()
                self.logger.info(f'done contest = {contest}')
