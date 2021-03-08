#!/usr/bin/env python

import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        season = self.get_season()

        url = self.url.split('?')[0].rstrip('/')
        standings_url = url + '/standings'
        problems_url = url + '/problems'

        result = {}
        problems_info = OrderedDict()

        try:
            page = REQ.get(problems_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}

        regex = '<table[^>]*id="contest_problem_list"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if match:
            html_table = match.group(0)
            table = parsed_table.ParsedTable(html_table)

            for r in table:
                short = r[''].value
                problem_info = problems_info.setdefault(short, {'short': short})

                problem_info['name'] = r['Name'].value
                url = r['Name'].column.node.xpath('.//a/@href')
                if url:
                    problem_info['url'] = urljoin(problems_url, url[0])

        page = REQ.get(standings_url)

        regex = '<table[^>]*id="standings"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)

        for r in table:
            row = {}
            problems = row.setdefault('problems', {})

            if 'Rk' in r:
                row['place'] = r.pop('Rk').value

            team = r.pop('Team')
            if isinstance(team, list):
                team, *more = team
                for addition in more:
                    classes = addition.column.node.xpath('@class')
                    if not classes:
                        continue
                    classes = classes[0].split()
                    if 'country-flag' in classes:
                        row['country'] = addition.column.node.xpath('.//img/@alt')[0]
                    elif 'university-logo' in classes:
                        row['university'] = addition.column.node.xpath('.//img/@alt')[0]

            if not team.value:
                continue

            url = team.column.node.xpath('.//a/@href')
            if url:
                row['member'] = url[0].split('/')[-1]
                row['name'] = team.value
            else:
                row['member'] = team.value + ' ' + season
                row['name'] = team.value

            if 'Slv.' in r:
                row['solving'] = int(r.pop('Slv.').value)
            elif 'Score' in r:
                row['solving'] = int(r.pop('Score').value)

            if 'Time' in r:
                row['penalty'] = int(r.pop('Time').value)

            for k, v in r.items():
                if len(k) > 1:
                    print('\n', k, v.value, standings_url, '\n')
                if len(k) == 1:
                    if not v.value:
                        continue

                    p = problems.setdefault(k, {})

                    attempt, *values = v.value.split()
                    if '+' in attempt:
                        attempt = sum(map(int, attempt.split('+')))
                    else:
                        attempt = int(attempt)
                    classes = v.column.node.xpath('@class')[0].split()

                    pending = 'pending' in classes
                    first = 'solvedfirst' in classes
                    solved = first or 'solved' in classes

                    if solved:
                        p['result'] = '+' if attempt == 1 else f'+{attempt - 1}'
                        p['time'] = self.to_time(int(values[0]), 2)
                    elif pending:
                        p['result'] = '?' if attempt == 1 else f'?{attempt - 1}'
                    else:
                        p['result'] = f'-{attempt}'

                    if first:
                        p['first_ac'] = True

            if not problems:
                continue

            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': ['university'],
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        @RateLimiter(max_calls=10, period=1)
        def fetch_profle_page(user):
            page, url = False, None
            if ' ' in user:
                return page, url
            url = resource.profile_url.format(account=user)
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    page = None
                else:
                    raise e
            return page, url

        with PoolExecutor(max_workers=10) as executor:
            for user, (page, url) in zip(users, executor.map(fetch_profle_page, users)):
                if pbar:
                    pbar.update()

                if page is None:
                    yield {'info': None}
                    continue

                if page is False:
                    yield {'info': {'_no_profile_url': True}}
                    continue

                info = {}
                match = re.search(r'<div[^>]*country-flag[^>]*>\s*<a[^>]*href="(?P<href>[^"]*)"', page)
                if match:
                    info['country'] = match.group('href').rstrip('/').split('/')[-1]

                match = re.search(r'<span[^>]*university-logo[^>]*>\s*<a[^>]*title="(?P<title>[^"]*)"', page)
                if match:
                    info['university'] = match.group('title')

                regex = '<table>.*?</table>'
                match = re.search(regex, page, re.DOTALL)
                if match:
                    html_table = match.group(0)
                    table = parsed_table.ParsedTable(html_table)
                    rows = list(table)
                    if len(rows) == 1:
                        row = rows[0]
                        for k, v in row.items():
                            try:
                                value = float(v.value)
                            except ValueError:
                                value = v.value
                            info[k.lower()] = value

                match = re.search(r'''<div[^>]*class="user-img"[^>]*url\('(?P<url>[^']*)'\)''', page)
                if match:
                    info['avatar_url'] = urljoin(url, match.group('url'))
                yield {'info': info}
