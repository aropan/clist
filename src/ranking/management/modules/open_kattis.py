#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from urllib.parse import urljoin, urlparse

from ratelimiter import RateLimiter
from tqdm import tqdm

from clist.models import Contest
from clist.templatetags.extras import as_number, get_item, slug
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import FailOnGetResponse


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        url = self.url.split('?')[0].rstrip('/')
        standings_url = url + '/standings'
        problems_url = url + '/problems'
        subdomain = urlparse(standings_url).netloc.split('.')[0]
        has_subdomain = subdomain not in ('open', 'kattis')

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
                short = r.pop('').value
                problem_info = problems_info.setdefault(short, {'short': short})

                if 'Name' in r:
                    name = r.pop('Name')
                    problem_info['name'] = name.value
                    url = name.column.node.xpath('.//a/@href')
                    if url:
                        url = urljoin(problems_url, url[0])
                        problem_info['url'] = url
                        code = url.rstrip('/').rsplit('/', 1)[-1]
                        if has_subdomain:
                            code = f'{subdomain}:{code}'
                        problem_info['code'] = code
                if r:
                    more_fields = problem_info.setdefault('_more_fields', {})
                    for k, v in r.items():
                        more_fields[slug(k, sep='_')] = as_number(v.value)

        page = REQ.get(standings_url)
        standings_urls = [standings_url]
        options = re.findall(r'value="(?P<option>\?filter=[0-9]+)"', page)
        for option in options:
            standings_urls.append(urljoin(standings_url, option))

        rows = []
        standings_kind = Contest.STANDINGS_KINDS['icpc']
        seen_urls = set()
        with PoolExecutor(max_workers=10) as executor:
            for page in executor.map(REQ.get, standings_urls):
                regex = '<table[^>]*class="[^"]*standings-table[^"]*"[^>]*>.*?</table>'
                entry = re.search(regex, page, re.DOTALL)
                html_table = entry.group(0)
                table = parsed_table.ParsedTable(html_table)

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
                        row['solving'] = as_number(r.pop('Slv.').value, force=True)
                    elif 'Score' in r:
                        row['solving'] = as_number(r.pop('Score').value, force=True)

                    if 'Time' in r:
                        row['penalty'] = int(r.pop('Time').value)

                    for k, v in r.items():
                        k, *other = k.split()
                        if len(k) == 1:
                            full_score = None
                            if other and (match := re.match(r'\((\d+)\)', other[0])):
                                full_score = int(match.group(1))
                                problems_info[k].setdefault('full_score', full_score)
                                standings_kind = Contest.STANDINGS_KINDS['scoring']

                            if not v.value:
                                continue

                            p = problems.setdefault(k, {})

                            score, *values = v.value.split()
                            if '+' in score:
                                score = sum(map(int, score.split('+')))
                            else:
                                score = as_number(score)
                            classes = v.column.node.xpath('@class')[0].split()

                            pending = 'pending' in classes
                            first = 'solvedfirst' in classes
                            first = first or bool(v.column.node.xpath('.//i[contains(@class,"cell-first")]'))
                            solved = first or 'solved' in classes
                            if options:
                                first = False

                            if not full_score:
                                if solved:
                                    p['result'] = '+' if score == 1 else f'+{score - 1}'
                                    p['time'] = self.to_time(int(values[0]), 2)
                                elif pending:
                                    p['result'] = '?' if score == 1 else f'?{score - 1}'
                                else:
                                    p['result'] = f'-{score}'
                            else:
                                p['result'] = score
                                p['partial'] = not solved and full_score > score

                            if first:
                                p['first_ac'] = True

                    if not problems:
                        continue

                    urls = team.column.node.xpath('.//a/@href')
                    assert len(urls) == 1
                    url = urls[0]
                    assert url.startswith('/contests/')
                    url = urljoin(standings_url, url)
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    row['_account_url'] = url
                    rows.append(row)
        if options:
            sorted_rows = sorted(rows, key=lambda x: (-x.get('solving', 0), x.get('penalty', 0)))
            last_rank = None
            last_score = None
            for rank, row in enumerate(sorted_rows, start=1):
                score = (row.get('solving', 0), row.get('penalty', 0))
                if last_score != score:
                    last_rank = rank
                    last_score = score
                row['place'] = last_rank

        with PoolExecutor(max_workers=10) as executor:
            split_team = get_item(self.resource.info, 'statistics.split_team', default=True)

            def fetch_members(row):
                page = REQ.get(row['_account_url'])

                entry = re.search(r'"team_members":\s*(?P<members>\[.*\]),?$', page, re.MULTILINE)
                members = json.loads(entry.group('members'))

                entry = re.search(r'"team_id":\s*"?(?P<team_id>[0-9]+)"?,$', page, re.MULTILINE)
                row['team_id'] = entry.group('team_id')

                for m in members:
                    if not m.get('username'):
                        m['username'] = f'hidden-user-{row["team_id"]}'
                    else:
                        m['profile_url'] = {'subdomain': subdomain, 'account': m['username']}

                if has_subdomain:
                    for m in members:
                        m['username'] = f'{subdomain}:{m["username"]}'

                row['_members'] = [{'account': m['username'], 'name': m['name']} for m in members]

                return members, row

            for members, row in executor.map(fetch_members, rows):
                real_members = [m for m in members if m['username']]
                if real_members:
                    members = real_members

                if split_team:
                    for member in members:
                        row['member'] = member['username']
                        account_info = row.setdefault('info', {})
                        account_info['name'] = member['name']
                        account_info['profile_url'] = member.get('profile_url')
                        result[row['member']] = deepcopy(row)
                else:
                    for member in row['_members']:
                        member.pop('account', None)
                    member = f'team-{row["team_id"]}'
                    if has_subdomain:
                        member = f'{subdomain}:{member}'
                    row['member'] = member
                    row.pop('team_id')
                    row.pop('_account_url')
                    result[member] = deepcopy(row)

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': ['university'],
            'standings_kind': standings_kind,
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

                if 'score' in info and (score := as_number(info.pop('score'), force=True)) is not None:
                    info['rating'] = score
                if 'rank' in info and (rank := as_number(info.pop('rank'), force=True)) is not None:
                    info['rank'] = rank

                yield {'info': info}
