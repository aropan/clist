#!/usr/bin/env python

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from urllib.parse import urljoin

from ratelimiter import RateLimiter
from tqdm import tqdm

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

        team_id = 0
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

            urls = team.column.node.xpath('.//a/@href')
            if not urls:
                row['member'] = team.value + ' ' + season
                row['name'] = team.value
                result[row['member']] = row
                continue

            commas = team.value.count(',')
            members = [url.split('/')[-1] for url in urls]
            row['name'] = re.sub(r'\s+,', ',', team.value)
            if len(members) > 1 or commas:
                row['_members'] = [{'account': m} for m in members]
                team_id += 1
                row['team_id'] = team_id
            for member in members:
                row['member'] = member
                result[row['member']] = deepcopy(row)

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': ['university'],
        }
        return standings

    @staticmethod
    def get_all_users_infos():
        base_url = 'https://open.kattis.com/ranklist'
        page = REQ.get(base_url)
        users = set()

        def parse_users(page):
            nonlocal users
            matches = re.finditer('<a[^>]*href="/users/(?P<member>[^"/]*)"[^>]*>(?P<name>[^<]*)</a>', page)
            for match in matches:
                member = match.group('member')
                if member in users:
                    continue
                users.add(member)
                name = match.group('name').strip()
                yield {'member': member, 'info': {'name': name}}

        yield from parse_users(page)

        urls = re.findall(r'url\s*:\s*(?P<url>"[^"]+")', page)

        def fetch_url(url):
            url = json.loads(url)
            url = urljoin(base_url, url)
            page = REQ.get(url)
            yield from parse_users(page)

        with PoolExecutor(max_workers=10) as executor, tqdm(total=len(urls), desc='urls') as pbar:
            for gen in executor.map(fetch_url, urls):
                yield from gen
                pbar.update()

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        if not users:
            yield from Statistic.get_all_users_infos()

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
                for field, regex in (
                    ('country', r'<div[^>]*country-flag[^>]*>\s*<a[^>]*href="[^"]*/countries/(?P<val>[^"/]*)/?"'),
                    ('subdivision', r'<div[^>]*subdivision-flag[^>]*>\s*<[^>]*>\s*<a[^>]*title="(?P<val>[^"]*)"'),
                    ('university', r'<span[^>]*university-logo[^>]*>\s*<a[^>]*title="(?P<val>[^"]*)"'),
                ):
                    match = re.search(regex, page)
                    if match:
                        info[field] = match.group('val')

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
                if 'score' in info:
                    info['rating'] = int(info['score'])
                if 'rank' in info:
                    info['rank'] = int(info['rank'])

                yield {'info': info}
