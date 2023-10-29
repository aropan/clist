#!/usr/bin/env python3

import hashlib
import operator
from collections import OrderedDict, defaultdict
from datetime import timedelta
from logging import getLogger
from pprint import pprint  # noqa

import tqdm
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.timezone import now

from clist.models import Contest, Resource
from clist.templatetags.extras import as_number, get_item, get_problem_key, get_problem_short, is_solved
from clist.views import update_problems
from logify.models import EventLog, EventStatus
from utils.attrdict import AttrDict
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


def get_statistics(contest):
    statistics = contest.statistics_set.all()
    statistics = statistics.select_related('account')
    statistics = statistics.filter(place_as_int__isnull=False)
    statistics = statistics.order_by('place_as_int', 'pk')
    return statistics


def get_info_key(statistic):
    division = statistic.addition.get('division')
    return (statistic.contest_id, division)


def is_skip(contest, statistic):
    old_rating_only = get_item(contest.resource.info, 'problems.rating.old_rating_only')
    old_rating_only = not args.ignore_old_rating_only and old_rating_only

    return bool(
        statistic.account.info.get('is_team') and not statistic.account.info.get('members')
        or statistic.addition.get('team_id') and not statistic.addition.get('_members')
        or old_rating_only and statistic.get_old_rating() is None
    )


def get_team(statistic):
    if 'team_id' in statistic.addition and statistic.addition.get('_members'):
        team_id = statistic.addition['team_id']
        handles = [m['account'] for m in statistic.addition['_members']]
    elif statistic.account.info.get('is_team') and statistic.account.info.get('members'):
        team_id = statistic.account.pk
        handles = statistic.account.info['members']
    else:
        team_id, handles = None, None
    return team_id, handles


def get_solved(result, problem):
    score = max(0, as_number(result.get('result', 0), force=True) or 0)
    if is_solved(result):
        return 1
    elif result.get('partial') and problem.get('full_score'):
        return score / problem['full_score']
    elif problem.get('max_score'):
        return score / problem['max_score']
    elif problem.get('min_score') and score:
        return problem['min_score'] / score
    elif str(result.get('result', '')).startswith('?'):
        return False
    else:
        return 0


def account_get_old_rating(account, before):
    ret = (
        account.statistics_set
        .filter(contest__end_time__lt=before.end_time)
        .filter(Q(addition__new_rating__isnull=False) | Q(addition__old_rating__isnull=False))
        .filter(contest__stage__isnull=True)
        .filter(contest__kind=before.kind)
        .order_by('-contest__end_time')
        .annotate(rating=JSONF('addition__new_rating'))
        .values_list('rating', flat=True)
        .first()
    )
    if ret is None:
        ret = before.resource.avg_rating
    return ret


def account_get_n_contests(account, before):
    ret = (
        account.statistics_set
        .filter(contest__end_time__lt=before.end_time)
        .filter(contest__stage__isnull=True)
        .filter(contest__kind=before.kind)
        .count()
    )
    return ret


def adjust_rating(adjustment, account, rating, n_contests):
    if not adjustment:
        return rating

    if 'filter' in adjustment:
        field = adjustment['filter']['field']
        if field in account.info:
            op = getattr(operator, adjustment['filter']['operator'])
            if not op(account.info[field], adjustment['filter']['value']):
                return rating

    if n_contests and n_contests <= len(adjustment):
        rating += adjustment['deltas'][n_contests - 1]

    return rating


class Command(BaseCommand):
    help = 'Calculate problem rating'
    VERSION = 'v2'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.calculate_problem_rating')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host names to calculate')
        parser.add_argument('-c', '--contest', metavar='CONTEST', type=int, help='contest id')
        parser.add_argument('-cs', '--contests', metavar='CONTESTS', nargs='*', type=int, help='contest ids')
        parser.add_argument('-s', '--search', metavar='TITLE', help='contest title regex')
        parser.add_argument('-l', '--limit', metavar='LIMIT', type=int, help='number of contests limit')
        parser.add_argument('-f', '--force', action='store_true', help='force update')
        parser.add_argument('-n', '--dryrun', action='store_true', help='do not update')
        parser.add_argument('-o', '--onlynew', action='store_true', help='update new only')
        parser.add_argument('--staleness', metavar='DAYS', type=int, help='lower end_time days limit')
        parser.add_argument('--update-contest-on-missing-account', action='store_true')
        parser.add_argument('--ignore-missing-account', action='store_true')
        parser.add_argument('--ignore-old-rating-only', action='store_true')
        parser.add_argument('--reparse', action='store_true', default=False, help='Reparse problem rating')

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
            resources = resources.filter(has_problem_rating=True)

        contests = Contest.objects.filter(resource__in=resources, stage__isnull=True)
        if args.search:
            contests = contests.filter(title__regex=args.search)
        if args.contest:
            contests = contests.filter(pk=args.contest)
        if args.contests:
            contests = contests.filter(pk__in=args.contests)
        if args.staleness:
            contests = contests.filter(updated__lt=now() - timedelta(days=args.staleness))
        if args.reparse:
            contests = contests.filter(info___reparse_problem_rating=True)

        contests = contests.order_by('-end_time')
        contests = contests.filter(end_time__lt=now())
        contests = contests.exclude(problem_set=None)
        contests = contests.select_related('resource')
        if args.onlynew:
            contests = contests.filter(info___problems_ratings_hash__isnull=True)
        if args.limit:
            contests = contests[:args.limit]

        ratings = []
        n_empty = 0
        n_done = 0
        n_total = 0
        n_skip_hash = 0
        n_skip_missing = 0
        for contest in tqdm.tqdm(contests, total=contests.count(), desc='contests'):
            resource = contest.resource
            rating_adjustment = resource.info.get('ratings', {}).get('adjustment')
            problems_ratings_info = resource.info.get('ratings', {}).get('problems', {})
            ignore_missing_account = (
                args.ignore_missing_account
                or problems_ratings_info.get('ignore_missing_account')
            )

            if not contest.is_major_kind():
                self.logger.warning(f'skip not major kind contest = {contest}')
                continue
            n_total += 1

            event_log = EventLog.objects.create(name='calculate_problem_rating',
                                                related=contest,
                                                status=EventStatus.IN_PROGRESS)

            statistics = get_statistics(contest)

            self.logger.info(f'number of statistics = {statistics.count()}, contest = {contest}')

            problems_contests = OrderedDict()
            problems_contests[contest] = statistics
            for problem in contest.problem_set.all():
                for problem_contest in problem.contests.select_related('resource').all():
                    if problem_contest not in problems_contests:
                        problems_contests[problem_contest] = get_statistics(problem_contest)

            rows_values = []
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='rows_values'):
                    if is_skip(current_contest, stat):
                        continue

                    problems = current_contest.info['problems']
                    if 'division' in problems:
                        problems = problems['division'][stat.addition.get('division')]

                    row = []
                    for problem in problems:
                        key = get_problem_key(problem)
                        short = get_problem_short(problem)
                        result = stat.addition.get('problems', {}).get(short, {})
                        row.append((key, get_solved(result, problem)))
                    row.sort()
                    row_value = (get_info_key(stat), stat.account_id) + tuple(row)
                    rows_values.append(row_value)
            if not rows_values:
                n_empty += 1
                self.logger.warning(f'skip empty contest = {contest}')
                event_log.update_status(EventStatus.SKIPPED, message='empty contest')
                contest.info.pop('_reparse_problem_rating', None)
                contest.save(update_fields=['info'])
                continue

            rows_values = tuple(sorted(rows_values))
            problems_ratings_value = (self.VERSION, rows_values)
            problems_ratings_hash = hashlib.sha256(str(problems_ratings_value).encode('utf8')).hexdigest()
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
                n_skip_hash += 1
                self.logger.warning(f'skip unchanged hash contest = {contest}')
                event_log.update_status(EventStatus.SKIPPED, message='unchanged hash')
                contest.info.pop('_reparse_problem_rating', None)
                contest.save(update_fields=['info'])
                continue

            contests_divisions_data = dict()
            stats = dict()
            team_ids = set()
            missing_account = False
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='old_ratings'):
                    if is_skip(current_contest, stat):
                        continue

                    team_id, handles = get_team(stat)
                    if team_id is not None:
                        if team_id in team_ids:
                            continue
                        team_ids.add(team_id)
                        ratings = []
                        n_contests_values = []
                        for handle in handles:
                            account = resource.account_set.filter(key=handle).first()
                            if account is None:
                                self.logger.info(f'missing account = {handle}')
                                if not missing_account and args.update_contest_on_missing_account:
                                    current_contest.statistic_timing = None
                                    current_contest.save()
                                missing_account = True

                                if not ignore_missing_account:
                                    break
                                old_rating = resource.avg_rating
                                n_contests = 0
                            else:
                                old_rating = account_get_old_rating(account, current_contest)
                                n_contests = account_get_n_contests(account, current_contest)
                                old_rating = adjust_rating(rating_adjustment, account, old_rating, n_contests)
                            ratings.append((1, old_rating))
                            n_contests_values.append(n_contests)
                        if missing_account and not ignore_missing_account:
                            break
                        if not ratings:
                            continue
                        old_rating = get_rating(ratings, target=0.5)
                        n_contests = max(n_contests_values)
                    else:
                        old_rating = stat.get_old_rating()
                        if old_rating is None:
                            old_rating = account_get_old_rating(stat.account, current_contest)
                        n_contests = account_get_n_contests(stat.account, current_contest)
                        old_rating = adjust_rating(rating_adjustment, stat.account, old_rating, n_contests)

                    weight = 1 - 0.9 ** (n_contests + 1)

                    stats[stat.pk] = dict(old_rating=old_rating, weight=weight)

                    info = contests_divisions_data.setdefault(get_info_key(stat), {
                        'wratings': [],
                        'places': defaultdict(int),
                        'orders': {},
                    })
                    info['wratings'].append((1, old_rating))
                    info['places'][stat.place_as_int] += 1

            if missing_account and not ignore_missing_account:
                n_skip_missing += 1
                self.logger.warning(f'skip by missing account = {contest}')
                event_log.update_status(EventStatus.SKIPPED, message='missing account')
                contest.info.pop('_reparse_problem_rating', None)
                contest.save(update_fields=['info'])
                continue

            for info in contests_divisions_data.values():
                rank = 0
                for place, size in sorted(info['places'].items()):
                    info['orders'][place] = rank + size / 2
                    rank += size

            problems_infos = dict()
            caches = dict()
            skip_problems = set()
            for current_contest, current_statistics in problems_contests.items():
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='perfomances'):
                    if is_skip(current_contest, stat):
                        continue

                    team_id, _ = get_team(stat)
                    if team_id is not None:
                        if team_id not in team_ids:
                            continue
                        team_ids.remove(team_id)

                    info = contests_divisions_data[get_info_key(stat)]
                    cache = caches.setdefault(get_info_key(stat), {})
                    perfomance = get_rating(info['wratings'], info['orders'][stat.place_as_int], cache=cache)
                    rating = (perfomance + stats[stat.pk]['old_rating']) / 2

                    problems = current_contest.info['problems']
                    if 'division' in problems:
                        problems = problems['division'][stat.addition.get('division')]

                    has_rating = 'new_rating' in stat.addition or 'rating_change' in stat.addition
                    weight = stats[stat.pk]['weight']
                    if not has_rating:
                        weight *= 0.5

                    for problem in problems:
                        key = get_problem_key(problem)
                        if contest.pk != current_contest.pk and key not in problems_infos:
                            continue
                        short = get_problem_short(problem)
                        result = stat.addition.get('problems', {}).get(short, {})
                        solved = get_solved(result, problem)
                        if solved is False:
                            skip_problems.add(key)
                            continue
                        problem_info = problems_infos.setdefault(key, {'wratings': [], 'solved': 0})
                        problem_info['wratings'].append((weight, rating))
                        problem_info['solved'] += weight * solved

            problems_ratings = {}
            for problem_key, problem_info in problems_infos.items():
                if problem_key in skip_problems:
                    continue
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
                    problem['rating'] = problems_ratings.get(key)
                update_problems(contest, problems, force=True)
                contest.info['_problems_ratings_hash'] = problems_ratings_hash
                contest.save()
                n_done += 1
                self.logger.info(f'done contest = {contest}')
                event_log.update_status(EventStatus.COMPLETED)
                contest.info.pop('_reparse_problem_rating', None)
                contest.save(update_fields=['info'])
        self.logger.info(f'done = {n_done}, skip hash = {n_skip_hash}, skip missing = {n_skip_missing}'
                         f', skip empty = {n_empty} of total = {n_total}')
