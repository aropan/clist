#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import arrow

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, *args, **kwargs):
        is_private = '/private/' in self.url
        func = self._get_private_standings if is_private else self._get_global_standings
        standings = func(*args, **kwargs)

        for row in standings['result'].values():
            for problem in row.get('problems', {}).values():
                rank = problem['rank']
                if rank == 1:
                    problem['first_ac'] = True
                if rank <= 3:
                    medal = ['gold', 'silver', 'bronze'][rank - 1]
                    problem['medal'] = medal
                    problem['_class'] = f'{medal}-medal'

                    if is_private:
                        key = f'n_{medal}_problems'
                        row.setdefault(key, 0)
                        row[key] += 1
        return standings

    def _get_private_standings(self, users=None, statistics=None):
        REQ.add_cookie('session', conf.ADVENTOFCODE_SESSION, '.adventofcode.com')
        page = REQ.get(self.url.rstrip('/') + '.json')
        data = json.loads(page)

        year = int(data['event'])

        problems_infos = OrderedDict()
        times = defaultdict(list)

        def items_sort(d):
            return sorted(d.items(), key=lambda i: int(i[0]))

        result = {}
        total_members = len(data['members'])
        tz = timezone(timedelta(hours=-5))
        for r in data['members'].values():
            handle = str(r.pop('id'))
            row = result.setdefault(handle, OrderedDict())
            row['_skip_for_problem_stat'] = True
            row['member'] = handle
            row['solving'] = r.pop('local_score')
            row['name'] = r.pop('name')
            row['stars'] = r.pop('stars')
            ts = int(r.pop('last_star_ts'))
            if ts:
                row['last_star'] = ts
            solutions = r.pop('completion_day_level')
            problems = row.setdefault('problems', OrderedDict())
            for day, solution in items_sort(solutions):
                if not solution:
                    continue
                day = str(day)
                for star, res in items_sort(solution):
                    star = str(star)
                    k = f'{day}.{star}'
                    if k not in problems_infos:
                        problems_infos[k] = {'name': day,
                                             'code': k,
                                             'group': day,
                                             'subname': '*',
                                             'subname_class': 'first-star' if star == '1' else 'both-stars',
                                             'url': urljoin(self.url, f'/{year}/day/{day}'),
                                             '_order': (int(day), int(star)),
                                             'ignore': True}

                    day_start_time = datetime(year=year, month=12, day=int(day), tzinfo=tz)
                    time = datetime.fromtimestamp(res['get_star_ts'], tz=timezone.utc)

                    ts = (time - day_start_time.replace(day=1)).total_seconds()
                    times[k].append(ts)

                    problems[k] = {
                        'ts': ts,
                        'time': self.to_time(time - day_start_time),
                        'absolute_time': self.to_time(ts),
                    }
            if not problems:
                result.pop(handle)

        for v in times.values():
            v.sort()

        for row in result.values():
            problems = row.setdefault('problems', {})
            for k, p in row['problems'].items():
                ts = p.pop('ts')
                rank = times[k].index(ts) + 1
                score = total_members - rank + 1
                p['rank'] = rank
                p['time_in_seconds'] = ts
                p['result'] = score

        last = None
        for idx, r in enumerate(sorted(result.values(), key=lambda r: -r['solving']), start=1):
            if r['solving'] != last:
                last = r['solving']
                rank = idx
            r['place'] = rank

        problems = list(sorted(problems_infos.values(), key=lambda p: p['_order']))
        for p in problems:
            p.pop('_order')

        ret = {
            'hidden_fields': {'last_star', 'stars', 'ranks'},
            'options': {
                'fixed_fields': [f'n_{medal}_problems' for medal in ['gold', 'silver', 'bronze']],
            },
            'result': result,
            'fields_types': {'last_star': ['timestamp']},
            'problems': problems,
        }

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

    def _get_global_standings(self, users=None, statistics=None):
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
        problem_name = match.group('problem_name').strip('-').strip()

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
                }

            problem = row.setdefault('problems', {}).setdefault(k, {})
            problem['result'] = score
            time = f'''{self.start_time.year} {match.group('time')} -05:00'''
            time = arrow.get(time, 'YYYY MMM D  HH:mm:ss ZZ') - self.start_time
            problem['time'] = self.to_time(time)
            problem['rank'] = rank
            problem['absolute_time'] = self.to_time(time + self.start_time - self.start_time.replace(day=1))

        problems = list(reversed(problems_info.values()))
        problems[0].update({'subname': '*', 'subname_class': 'first-star'})
        if len(problems) > 1:
            problems[1].update({'subname': '*', 'subname_class': 'both-stars'})

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
