#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import arrow
import tqdm

from clist.models import Contest
from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule
from ranking.models import Account, VirtualStart


class Statistic(BaseModule):

    def get_standings(self, *args, **kwargs):
        is_private = '/private/' in self.url
        func = self._get_private_standings if is_private else self._get_global_standings
        standings = func(*args, **kwargs)

        self._set_medals(standings['result'], n_medals=is_private)
        return standings

    @staticmethod
    def _set_medals(result, n_medals=False):
        for row in result.values():
            for problem in row.get('problems', {}).values():
                rank = problem['rank']
                if rank == 1:
                    problem['first_ac'] = True
                if rank <= 3:
                    medal = ['gold', 'silver', 'bronze'][rank - 1]
                    problem['medal'] = medal
                    problem['_class'] = f'{medal}-medal'

                    if n_medals:
                        key = f'n_{medal}_problems'
                        row.setdefault(key, 0)
                        row[key] += 1

    def _get_private_standings(self, users=None, **kwargs):
        REQ.add_cookie('session', conf.ADVENTOFCODE_SESSION, '.adventofcode.com')
        page = REQ.get(self.url.rstrip('/') + '.json')
        data = json.loads(page)

        year = int(data['event'])

        problems_infos = OrderedDict()

        def items_sort(d):
            return sorted(d.items(), key=lambda i: int(i[0]))

        result = defaultdict(dict)
        total_members = len(data['members'])
        local_best_score = total_members
        global_best_score = 100
        tz = timezone(timedelta(hours=-5))

        contests = Contest.objects.filter(resource=self.resource, slug__startswith=f'advent-of-code-{year}-day-')
        contests = {c.start_time: c for c in contests}

        handles = {str(r['id']) for r in data['members'].values()}
        qs = Account.objects.filter(resource=self.resource, key__in=handles, coders__isnull=False)
        qs = qs.values('coders', 'key')
        account_coders = defaultdict(list)
        for a in qs:
            account_coders[a['key']].append(a['coders'])

        has_virtual = False
        divisions_order = []
        for division in 'diff', 'virtual', 'main':
            is_main = division == 'main'
            is_virtual = division == 'virtual'
            is_diff = division == 'diff'
            times = defaultdict(list)
            rows = list(data['members'].values())
            division_result = {}
            for r in tqdm.tqdm(rows, total=len(rows)):
                r = deepcopy(r)
                handle = str(r.pop('id'))
                row = division_result.setdefault(handle, OrderedDict())
                row['_skip_for_problem_stat'] = True
                row['_global_score'] = r.pop('global_score')
                if not is_diff:
                    row['global_score'] = 0
                row['member'] = handle
                row['_local_score'] = r.pop('local_score')
                row['name'] = r.pop('name')
                row['stars'] = r.pop('stars')
                ts = int(r.pop('last_star_ts'))
                if ts:
                    row['last_star'] = ts
                solutions = r.pop('completion_day_level')
                if not solutions:
                    division_result.pop(handle)
                    continue

                if is_virtual and handle in account_coders:
                    virtual_starts = VirtualStart.filter_by_content_type(Contest)
                    virtual_starts = virtual_starts.filter(object_id__in={c.pk for c in contests.values()},
                                                           coder__in=account_coders[handle])
                    virtual_starts = {vs.entity.start_time: vs.start_time for vs in virtual_starts}
                else:
                    virtual_starts = {}

                problems = row.setdefault('problems', OrderedDict())
                for day, solution in items_sort(solutions):
                    if not solution:
                        continue
                    day = str(day)
                    day_start_time = datetime(year=year, month=12, day=int(day), tzinfo=tz)
                    contest = contests[day_start_time]

                    prev_time_in_seconds = None
                    for star, res in items_sort(solution):
                        star = str(star)
                        k = f'{day}.{star}'
                        if k not in problems_infos:
                            problems_infos[k] = {'name': contest.title.split('. ', 3)[-1],
                                                 'short': k,
                                                 'code': f'Y{year}D{day}',
                                                 'group': day,
                                                 'subname': '*',
                                                 'subname_class': 'first-star' if star == '1' else 'both-stars',
                                                 'url': urljoin(self.url, f'/{year}/day/{day}'),
                                                 '_order': (-int(day), int(star)),
                                                 'skip_in_stats': True}
                            if star == '1':
                                problems_infos[k]['skip_for_divisions'] = ['diff']

                        time = datetime.fromtimestamp(res['get_star_ts'], tz=timezone.utc)

                        virtual_start = virtual_starts.get(contest.start_time)
                        if is_virtual and virtual_start and day_start_time < virtual_start < time:
                            time -= virtual_start - day_start_time
                            has_virtual = True
                            problem_is_virtual = True
                        else:
                            problem_is_virtual = False

                        time_in_seconds = (time - day_start_time.replace(day=1)).total_seconds()
                        if is_diff:
                            if star == '1':
                                prev_time_in_seconds = time_in_seconds
                                continue
                            time_in_seconds = time_in_seconds - prev_time_in_seconds
                            time = day_start_time + timedelta(seconds=time_in_seconds)
                            time_in_seconds = (time - day_start_time.replace(day=1)).total_seconds()
                            prev_time_in_seconds = None

                        problem = {
                            'time_index': res['star_index'],
                            'time_in_seconds': time_in_seconds,
                            'time': self.to_time(time - day_start_time),
                            'absolute_time': self.to_time(time_in_seconds),
                            'result_name': '*',
                            'result_name_class': 'first-star' if star == '1' else 'both-stars',
                            '_solution_priority': 2 if star == '1' else 1,
                        }
                        if prev_time_in_seconds:
                            problem['delta_time'] = '+' + self.to_time(time_in_seconds - prev_time_in_seconds)
                        if problem_is_virtual:
                            problem['is_virtual'] = True
                        problems[k] = problem

                        times[k].append((problem['time_in_seconds'], problem['time_index']))
                        prev_time_in_seconds = time_in_seconds
                if not problems:
                    division_result.pop(handle)

            global_times = deepcopy(times)
            for contest in contests.values():
                day = contest.key.split()[-1]
                for stat in contest.statistics_set.values('addition__problems', 'account__key'):
                    account = stat['account__key']
                    for star, p in stat['addition__problems'].items():
                        star = 3 - int(star)
                        k = f'{day}.{star}'
                        if account in division_result and k in division_result[account]['problems']:
                            division_result[account]['problems'][k].update({
                                'global_rank': p['rank'],
                                'global_score': p['result'],
                            })
                        elif 'time_in_seconds' in p:
                            global_times[k].append((p['time_in_seconds'], -1))
            for t in (times, global_times):
                for v in t.values():
                    v.sort()
            for row in division_result.values():
                problems = row.setdefault('problems', {})
                for k, p in row['problems'].items():
                    time_value = (p['time_in_seconds'], p['time_index'])
                    rank = times[k].index(time_value) + 1
                    score = max(local_best_score - rank + 1, 0)
                    p['rank'] = rank
                    p['result'] = score
                    p['result_rank'] = rank

                    if not is_diff:
                        global_rank = global_times[k].index(time_value) + 1
                        global_score = max(global_best_score - global_rank + 1, 0)
                        if global_score and 'global_rank' not in p:
                            p['global_rank'] = global_rank
                            p['global_score'] = global_score
                        row['global_score'] += p.get('global_score', 0)

            for row in division_result.values():
                row['solving'] = sum(p['result'] for p in row['problems'].values())

            last = None
            for idx, r in enumerate(sorted(division_result.values(), key=lambda r: -r['solving']), start=1):
                if r['solving'] != last:
                    last = r['solving']
                    rank = idx
                r['place'] = rank

            if is_main:
                for k, v in division_result.items():
                    result[k].update(v)
            else:
                if is_virtual and not has_virtual:
                    continue
                self._set_medals(division_result, n_medals=True)
                for k, v in division_result.items():
                    result[k].setdefault('_division_addition', {}).update({division: v})
            divisions_order.append(division)

        problems = list(sorted(problems_infos.values(), key=lambda p: p['_order']))
        for p in problems:
            p.pop('_order')

        ret = {
            'hidden_fields': {'last_star', 'stars', 'ranks', 'local_score'},
            'options': {
                'fixed_fields': ['global_score'] + [f'n_{medal}_problems' for medal in ['gold', 'silver', 'bronze']],
                'alternative_result_field': 'global_score',
            },
            'result': result,
            'fields_types': {'last_star': ['timestamp']},
            'problems': problems,
        }
        if len(divisions_order) > 1:
            ret['divisions_order'] = divisions_order[::-1]

        now = datetime.now(tz=tz)
        if now.year == year and now.month == 12:
            start = now.replace(hour=0, minute=0, second=0)
            delta = start - now
            if delta < timedelta():
                delta += timedelta(days=1, seconds=42)

            if delta > timedelta(hours=23):
                delta = timedelta(minutes=1)
            else:
                delta = min(delta, timedelta(minutes=30))

            ret['timing_statistic_delta'] = delta

        return ret

    def _get_global_standings(self, users=None, **kwargs):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        ret = {}

        if '/day/' not in self.url:
            match = re.search(r'\bday\b\s+(?P<day>[0-9]+)', self.name, re.IGNORECASE)
            contest_url = self.url.rstrip('/') + '/day/' + match['day']
        else:
            contest_url = self.url

        page = REQ.get(contest_url)
        match = re.search(r'<h2>[^<]*Day\s*(?P<day>[0-9]+):\s*(?P<problem_name>[^<]*)</h2>', page)
        day = match.group('day')
        problem_name = html.unescape(match.group('problem_name').strip('-').strip())

        if self.name.count('.') == 1 and problem_name:
            ret['title'] = f'{self.name}. {problem_name}'

        standings_url = self.standings_url or contest_url.replace('/day/', '/leaderboard/day/')
        page = REQ.get(standings_url)

        matches = re.finditer(
            r'''
            <div[^>]*class="leaderboard-entry"[^>]*data-user-id="(?P<user_id>[^"]*)"[^>]*>\s*
                <span[^>]*class="leaderboard-position"[^>]*>\s*(?P<rank>[0-9]+)[^<]*</span>\s*
                <span[^>]*class="leaderboard-time"[^>]*>(?P<time>[^<]*)</span>\s*
                (?:<a[^>]*href="(?P<href>[^"]*)"[^>]*>\s*)?
                <span[^>]*class="leaderboard-userphoto"[^>]*>(\s*<img[^>]*src="(?P<avatar>[^"]*)"[^>]*>)?[^<]*</span>\s*
                (?:<span[^>]*class="leaderboard-anon"[^>]*>)?(?P<name>[^<]*)
            ''',
            page,
            re.VERBOSE
        )

        problems_info = OrderedDict()

        result = {}
        last = None
        n_problems = 0
        n_results = 0
        for match in matches:
            n_results += 1
            name = html.unescape(match.group('name')).strip()
            handle = match.group('user_id')

            rank = int(match.group('rank'))
            if last is None or last >= rank:
                n_problems += 1
            last = rank

            row = result.setdefault(handle, {'solving': 0, '_skip_for_problem_stat': True})
            score = 100 - rank + 1
            row['solving'] += score
            row['name'] = name
            row['member'] = handle

            avatar = match.group('avatar')
            if avatar:
                row['info'] = {'avatar': avatar}

            k = str(n_problems)
            if k not in problems_info:
                problems_info[k] = {
                    'name': problem_name,
                    'short': k,
                    'code': f'Y{year}D{day}',
                    'url': contest_url,
                    'group': 0,
                    '_info_prefix_fields': ['first_ac', 'last_ac'],
                }

            problems = row.setdefault('problems', {})
            problem = problems.setdefault(k, {})
            problem['result'] = score
            time = f'''{self.start_time.year} {match.group('time')} -05:00'''
            time = arrow.get(time, 'YYYY MMM D  HH:mm:ss ZZ') - self.start_time
            problem['time'] = self.to_time(time)
            problem['rank'] = rank
            problem['time_in_seconds'] = (time + self.start_time - self.start_time.replace(day=1)).total_seconds()
            problem['absolute_time'] = self.to_time(problem['time_in_seconds'])
            problem['_solution_priority'] = 0

            prev_k = str(n_problems - 1)
            if prev_k in problems:
                prev_problem = problems[prev_k]
                delta_time = prev_problem['time_in_seconds'] - problem['time_in_seconds']
                prev_problem['delta_time'] = '+' + self.to_time(delta_time)

        problems = list(reversed(problems_info.values()))
        problems[0].update({'subname': '*', 'subname_class': 'first-star', '_info_prefix': 'first_star_'})
        if len(problems) > 1:
            problems[1].update({'subname': '*', 'subname_class': 'both-stars', '_info_prefix': 'both_stars_'})
            first_ac = defaultdict(lambda: float('inf'))
            last_ac = defaultdict(lambda: float('-inf'))
            for r in result.values():
                for k, v in r['problems'].items():
                    first_ac[k] = min(first_ac[k], v['time_in_seconds'])
                    last_ac[k] = max(last_ac[k], v['time_in_seconds'])
            problems[1].update({
                'diff_first_ac': self.to_time(first_ac['1'] - first_ac['2']),
                'diff_last_ac': self.to_time(last_ac['1'] - last_ac['2']),
            })

        place = None
        last = None
        for rank, row in enumerate(sorted(result.values(), key=lambda r: -r['solving']), start=1):
            score = row['solving']
            if last != score:
                place = rank
                last = score
            row['place'] = place

        ret.update({
            'contest_url': contest_url,
            'result': result,
            'url': standings_url,
            'problems': problems,
        })
        if n_results < 200:
            ret['timing_statistic_delta'] = timedelta(minutes=1)
        return ret
