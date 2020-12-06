#!/usr/bin/env python

import re
import html
from datetime import timedelta
from collections import OrderedDict

import arrow

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        ret = {}

        page = REQ.get(self.url)
        match = re.search(rf'<h2>[^<]*Day\s*[0-9]+:\s*(?P<problem_name>[^<]*)</h2>', page)
        problem_name = match.group('problem_name').strip('-').strip()

        if self.name.count('.') == 1 and problem_name:
            ret['title'] = f'{self.name}. {problem_name}'

        standings_url = self.standings_url or self.url.replace('/day/', '/leaderboard/day/')
        page = REQ.get(standings_url)

        matches = re.finditer(
            r'''
            <div[^>]*class="leaderboard-entry"[^>]*>\s*
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
            href = match.group('href')
            name = html.unescape(match.group('name')).strip()
            if href:
                handle = href.split('//')[-1].strip('/')
            elif re.match(r'^\(anonymous user #[0-9]+\)$', name):
                handle = name
            else:
                handle = f'{name}, {season}'
            handle = handle.replace('/', '-')

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
                problems_info[k] = {'name': problem_name, 'code': k, 'url': self.url, 'group': 0, 'full_score': 100}

            problem = row.setdefault('problems', {}).setdefault(k, {})
            problem['result'] = score
            time = f'''{self.start_time.year} {match.group('time')} -05:00'''
            problem['time'] = self.to_time(arrow.get(time, 'YYYY MMM D  HH:mm:ss ZZ') - self.start_time)
            if rank == 1:
                problem['first_ac'] = True

        problems = list(reversed(problems_info.values()))
        problems[0]['subname'] = 'first star'
        if len(problems) > 1:
            problems[1]['subname'] = 'both stars'

        place = None
        last = None
        for rank, row in enumerate(sorted(result.values(), key=lambda r: -r['solving']), start=1):
            score = row['solving']
            if last != score:
                place = rank
                last = score
            row['place'] = place

        ret.update({
            'result': result,
            'url': standings_url,
            'problems': problems,
        })
        if n_results < 200:
            ret['timing_statistic_delta'] = timedelta(minutes=5)
        return ret
