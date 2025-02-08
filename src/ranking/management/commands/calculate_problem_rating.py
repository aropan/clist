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
from sql_util.utils import SubqueryCount

from clist.models import Contest, Resource
from clist.templatetags.extras import as_number, get_item, get_problem_key, get_problem_short, is_solved
from clist.utils import update_problems
from logify.models import EventLog, EventStatus
from utils.attrdict import AttrDict
from utils.json_field import JSONF
from utils.rating import get_weighted_rating


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

    problems = contest.info.get('problems')
    division = statistic.addition.get('division')
    if isinstance(problems, dict) and 'division' in problems and division is None:
        return True

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


def get_solved(result, problem, not_full_multiplier=1e-3):
    score = max(0, as_number(result.get('result', 0), force=True) or 0)
    is_challenge = problem.get('is_challenge')
    result_is_solved = is_solved(result)
    if result_is_solved and not is_challenge:
        return 1
    elif result.get('partial') and problem.get('full_score'):
        ret = score / problem['full_score']
    elif problem.get('max_score'):
        ret = score / problem['max_score']
    elif problem.get('min_score') and score:
        ret = problem['min_score'] / score
    elif result_is_solved:
        return 1
    elif str(result.get('result', '')).startswith('?'):
        return False
    else:
        return 0
    if ret < 1 and not is_challenge:
        ret = ret * not_full_multiplier
    return ret


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


def statistics_get_n_contests(statistics, before):
    contest_filter = Q(
        contest__end_time__lt=before.end_time,
        contest__stage__isnull=True,
        contest__kind=before.kind,
    )
    qs = statistics.annotate(n_contests=SubqueryCount('account__statistics', filter=contest_filter))
    return {s['pk']: s['n_contests'] for s in qs.values('pk', 'n_contests')}


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
            contests = contests.filter(problem_rating_update_required=True)

        contests = contests.order_by('-end_time')
        contests = contests.filter(end_time__lt=now())
        contests = contests.exclude(problem_set=None)
        contests = contests.select_related('resource')
        if args.onlynew:
            contests = contests.filter(problem_rating_hash__isnull=True)
        if args.limit:
            contests = contests[:args.limit]

        contests_count = contests.count()
        if resources.count() == 1 and contests_count > 5:
            resource_event_log = EventLog.objects.create(name='calculate_problem_rating',
                                                         related=contests.first().resource,
                                                         status=EventStatus.IN_PROGRESS)
        else:
            resource_event_log = None

        ratings = []
        n_empty = 0
        n_done = 0
        n_total = 0
        n_skip_hash = 0
        n_skip_missing = 0
        n_contest_progress = 0
        for contest in tqdm.tqdm(contests, total=contests_count, desc='contests'):
            if resource_event_log:
                message = f'progress {n_contest_progress} of {contests_count} ({n_done} parsed), contest = {contest}'
                resource_event_log.update_message(message)
            n_contest_progress += 1

            resource = contest.resource
            rating_adjustment = resource.info.get('ratings', {}).get('adjustment')
            problem_rating_info = resource.info.get('ratings', {}).get('problems', {})
            ignore_missing_account = (
                args.ignore_missing_account
                or problem_rating_info.get('ignore_missing_account')
            )

            if not contest.is_major_kind():
                self.logger.warning(f'skip not major kind contest = {contest}')
                continue
            n_total += 1

            event_log = EventLog.objects.create(name='calculate_problem_rating',
                                                related=contest,
                                                status=EventStatus.IN_PROGRESS)

            problems_contests = OrderedDict()
            for problem in contest.problem_set.all():
                for problem_contest in problem.contests.select_related('resource').all():
                    if problem_contest.has_hidden_results:
                        self.logger.info(f'skip hidden results contest = {problem_contest}')
                        continue
                    if problem_contest.info.get('skip_problem_rating'):
                        continue
                    if problem_contest not in problems_contests:
                        statistics = get_statistics(problem_contest)
                        problems_contests[problem_contest] = statistics
                        self.logger.info(f'number of statistics = {statistics.count()}, contest = {problem_contest}')

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
                contest.problem_rating_update_done()
                continue

            rows_values = tuple(sorted(rows_values))
            problem_rating_value = (self.VERSION, rows_values)
            problem_rating_hash = hashlib.sha256(str(problem_rating_value).encode('utf8')).hexdigest()
            empty_problem_rating = False
            for problem in contest.problem_set.all():
                if problem.rating is None:
                    empty_problem_rating = True
                    break
            if (
                not empty_problem_rating and
                not args.force and
                contest.problem_rating_hash == problem_rating_hash
            ):
                n_skip_hash += 1
                self.logger.warning(f'skip unchanged hash contest = {contest}')
                event_log.update_status(EventStatus.SKIPPED, message='unchanged hash')
                contest.problem_rating_update_done()
                continue

            contests_divisions_data = dict()
            stats = dict()
            team_ids = set()
            missing_account = False
            for current_contest, current_statistics in problems_contests.items():

                accounts_to_get_n_contests = set()
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(),
                                      desc='accounts_to_get_n_contests'):
                    if is_skip(current_contest, stat):
                        continue
                    team_id, _ = get_team(stat)
                    if team_id is None:
                        accounts_to_get_n_contests.add(stat.account_id)
                filtered_statistics = current_statistics.filter(account_id__in=accounts_to_get_n_contests)
                n_contests_for_accounts = statistics_get_n_contests(filtered_statistics, current_contest)

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
                        old_rating = get_weighted_rating(ratings, target=0.5)
                        n_contests = max(n_contests_values)
                    else:
                        old_rating = stat.get_old_rating()
                        if old_rating is None:
                            old_rating = account_get_old_rating(stat.account, current_contest)
                        if stat.pk in n_contests_for_accounts:
                            n_contests = n_contests_for_accounts[stat.pk]
                        else:
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
                contest.problem_rating_update_done()
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
                for stat in tqdm.tqdm(current_statistics, total=current_statistics.count(), desc='performances'):
                    if is_skip(current_contest, stat):
                        continue

                    team_id, _ = get_team(stat)
                    if team_id is not None:
                        if team_id not in team_ids:
                            continue
                        team_ids.remove(team_id)

                    info = contests_divisions_data[get_info_key(stat)]
                    cache = caches.setdefault(get_info_key(stat), {})
                    performance = get_weighted_rating(info['wratings'], info['orders'][stat.place_as_int], cache=cache)
                    rating = (performance + stats[stat.pk]['old_rating']) / 2

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

            problem_ratings = {}
            for problem_key, problem_info in problems_infos.items():
                if problem_key in skip_problems:
                    continue
                rating = get_weighted_rating(problem_info['wratings'], problem_info['solved'])
                problem_ratings[problem_key] = round(rating)

            if not args.dryrun:
                problems = contest.info['problems']
                if 'division' in problems:
                    list_problems = []
                    for d in problems['division'].values():
                        list_problems.extend(d)
                else:
                    list_problems = problems
                rating_diff = dict()
                updated_rating = set()
                for problem in list_problems:
                    key = get_problem_key(problem)
                    rating = problem_ratings.get(key)
                    problem_rating = problem.get('rating')
                    if rating != problem_rating:
                        updated_rating.add(key)
                        if problem_rating and rating and key not in rating_diff:
                            rating_diff[key] = (rating, rating - problem_rating)
                    problem['rating'] = rating
                message = f'{len(updated_rating)} of {len(problem_ratings)} problems updated'
                if rating_diff:
                    rating_diff = dict(sorted(rating_diff.items(), key=lambda x: -abs(x[1][1])))
                    message += f', rating difference = {rating_diff}'
                update_problems(contest, problems, force=True)
                contest.problem_rating_hash = problem_rating_hash
                if args.force:
                    contest.save(update_fields=['problem_rating_hash'])
                else:
                    contest.save()
                n_done += 1
                self.logger.info(f'done {contest}: {message}')
                event_log.update_status(EventStatus.COMPLETED, message=message)
                contest.problem_rating_update_done()

        if resource_event_log:
            resource_event_log.delete()

        self.logger.info(f'done = {n_done}, skip hash = {n_skip_hash}, skip missing = {n_skip_missing}'
                         f', skip empty = {n_empty} of total = {n_total}')
