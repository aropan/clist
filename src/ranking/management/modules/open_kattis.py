#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from urllib.parse import urljoin

from ratelimiter import RateLimiter
from tqdm import tqdm

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
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

        regex = '<table[^>]*>.*?</table>'
        entry = re.search(regex, page, re.DOTALL)
        if entry:
            html_table = entry.group(0)
            table = parsed_table.ParsedTable(html_table)

            for r in table:
                short = r[''].value
                problem_info = problems_info.setdefault(short, {'short': short})

                problem_info['name'] = r['Name'].value
                url = r['Name'].column.node.xpath('.//a/@href')
                if url:
                    url = urljoin(problems_url, url[0])
                    problem_info['url'] = url
                    code = url.rstrip('/').rsplit('/', 1)[-1]
                    problem_info['code'] = code

        page = REQ.get(standings_url)

        regex = '<table[^>]*class="[^"]*standings-table[^"]*"[^>]*>.*?</table>'
        entry = re.search(regex, page, re.DOTALL)
        html_table = entry.group(0)
        table = parsed_table.ParsedTable(html_table)

        rows = []
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})

            if 'Rk' in r:
                row['place'] = r.pop('Rk').value

            team = r.pop('Team')
            if isinstance(team, list):
                if 'place' not in row:
                    v, *team = team
                    row['place'] = v.value
                team, *more = team
                for addition in more:
                    for img in addition.column.node.xpath('.//img'):
                        alt = img.attrib.get('alt', '')
                        if not alt:
                            continue
                        src = img.attrib.get('src', '')
                        if '/countries/' in src and 'country' not in row:
                            row['country'] = alt
                        elif '/universities/' in src and 'university' not in row:
                            row['university'] = alt
            if not team.value:
                continue

            row['name'] = team.value

            if 'Slv.' in r:
                row['solving'] = int(r.pop('Slv.').value)
            elif 'Score' in r:
                row['solving'] = int(r.pop('Score').value)

            if 'Time' in r:
                row['penalty'] = int(r.pop('Time').value)

            for k, v in r.items():
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
                    first = 'solvedfirst' in classes or bool(v.column.node.xpath('.//i[contains(@class,"cell-first")]'))
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
            assert len(urls) == 1
            url = urls[0]
            assert url.startswith('/contests/')
            row['_account_url'] = urljoin(standings_url, url)
            rows.append(row)

        with PoolExecutor(max_workers=10) as executor:

            def fetch_members(row):
                page = REQ.get(row['_account_url'])
                entry = re.search('"team_members":(?P<members>.*),$', page, re.MULTILINE)
                members = json.loads(entry.group('members'))

                row['_members'] = [{'account': m.get('username'), 'name': m['name']} for m in members]
                entry = re.search(r'"team_id":\s*"?(?P<team_id>[0-9]+)"?,$', page, re.MULTILINE)
                row['team_id'] = entry.group('team_id')
                return members, row

            for members, row in executor.map(fetch_members, rows):
                real_members = [m for m in members if m.get('username')]
                if real_members:
                    members = real_members

                for member in members:
                    row['member'] = member['username']
                    result[row['member']] = deepcopy(row)

        standings = {
            'result': result,
            'url': standings_url,
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
            entries = re.finditer('<a[^>]*href="/users/(?P<member>[^"/]*)"[^>]*>(?P<name>[^<]*)</a>', page)
            for entry in entries:
                member = entry.group('member')
                if member in users:
                    continue
                users.add(member)
                name = entry.group('name').strip()
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
                    yield {'delete': True}
                    continue

                if page is False:
                    yield {'info': {'_no_profile_url': True}}
                    continue

                info = {}
                for field, regex in (
                    ('name', r'<div[^>]*class="image_info-text-horizontal"[^>]*>\s*<a[^>]*>\s*<span[^>]*>\s*<em>(?P<val>[^<]*)'),  # noqa
                    ('country', r'<div[^>]*country-flag[^>]*>\s*<a[^>]*href="[^"]*/countries/(?P<val>[^"/]*)/?"'),
                    ('subdivision', r'<div[^>]*subdivision-flag[^>]*>\s*<[^>]*>\s*<a[^>]*title="(?P<val>[^"]*)"'),
                    ('university', r'<span[^>]*university-logo[^>]*>\s*<a[^>]*title="(?P<val>[^"]*)"'),

                    ('country', r'<div>\s*<a[^>]*href="[^"]*/countries/(?P<val>[^"/]*)/?"'),
                    ('subdivision', r'<div[^>]*>\s*<[^>]*>\s*<a[^>]*href="[^"]*/countries(?:/[^"/]*){,2}/?"[^>]*title="(?P<val>[^"]*)"'),  # noqa
                    ('university', r'<div[^>]*>\s*<a[^>]*href="[^"]*/universities/[^"]*"[^>]*title="(?P<val>[^"]*)"'),
                    ('name', r'<a[^>]*href="/users/[^"]*"[^>]*>[^<]*<span[^>]*>(?P<val>[^<]*)</span>'),
                ):
                    entry = re.search(regex, page)
                    if entry:
                        value = html.unescape(entry.group('val'))
                        info[field] = value

                regex = '<table>.*?</table>'
                entry = re.search(regex, page, re.DOTALL)
                if entry:
                    html_table = entry.group(0)
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
                entries = re.finditer(
                    r'''
                      <span[^>]*class="info_label"[^>]*>(?P<key>[^<]+)</span>\s*
                      <span[^>]*class="important_number"[^>]*>(?P<value>[^<]+)</span>
                    ''',
                    page,
                    re.VERBOSE,
                )
                for entry in entries:
                    k = entry.group('key').lower()
                    v = entry.group('value').strip()
                    if v:
                        info[k] = as_number(v)

                for regex in (
                    r'''<div[^>]*class="user-img"[^>]*url\('(?P<url>[^']*)'\)''',
                    r'<object[^>]*data="(?P<url>/images/users/[^"]*)"[^>]*>',
                ):
                    entry = re.search(regex, page)
                    if entry:
                        info['avatar_url'] = urljoin(url, entry.group('url'))
                        break

                if 'score' in info:
                    info['rating'] = int(info['score'])
                if 'rank' in info:
                    info['rank'] = int(info['rank'])

                yield {'info': info}
