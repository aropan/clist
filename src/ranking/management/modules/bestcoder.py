#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import json
import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

import tqdm
from ratelimiter import RateLimiter

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    STANDINGS_URL_FORMAT_ = '/contests/contest_ranklist.php?cid={key}'
    SOLUTION_URL_FORMAT_ = '/contests/getAjaxInfo.php?act=viewcode&cid={0}&rid={1}'
    SETTINGS_URL_ = '/setting.php'
    USER_RATING_API_URL_ = '/api/api.php?type=user-rating&user={0}'

    def get_standings(self, users=None, statistics=None):

        page = REQ.get(self.url)
        if 'login.php' in REQ.last_url:
            raise ExceptionParseStandings('private contest')

        table = parsed_table.ParsedTable(html=page, xpath='.//table[@id="contest-problems"]//tr')

        problems_infos = collections.OrderedDict()
        for r in table:
            p_info = {
                'short': r['Pro.ID'].value,
                'name': r['Title'].value,
            }
            href = r['Title'].column.node.xpath('.//a/@href')
            if href:
                p_info['url'] = urljoin(self.url, href[0])
            problems_infos[p_info['short']] = p_info

        standings_url = urljoin(self.url, self.STANDINGS_URL_FORMAT_.format(key=self.key))
        page = REQ.get(standings_url)
        matches = re.findall('"[^"]*contest_ranklist[^"]*page=([0-9]+)', page)
        n_pages = max(map(int, matches)) if matches else 1

        def fetch_page(page):
            url = f'{standings_url}&page={page + 1}'
            return REQ.get(url)

        results = {}
        header_mapping = {'Rank': 'place', 'User': 'member', 'Score': 'solving', 'Hack': 'hack'}
        with PoolExecutor(max_workers=4) as executor, tqdm.tqdm(total=n_pages, desc='paging') as pbar:
            for page in executor.map(fetch_page, range(n_pages)):
                table = parsed_table.ParsedTable(html=page,
                                                 xpath='.//table[@id="contest-ranklist"]//tr',
                                                 header_mapping=header_mapping)
                for r in table:
                    row = collections.OrderedDict()
                    problems = row.setdefault('problems', {})
                    for k, v in r.items():
                        p = k.split()
                        if p[0] not in problems_infos:
                            row[k] = v.value
                            continue
                        short, full_score = p
                        problems_infos[short].setdefault('full_score', full_score)
                        if not v.value:
                            continue

                        p = problems.setdefault(short, {})
                        score, *info = v.value.split()
                        p['result'] = score
                        if score.startswith('-'):
                            continue

                        if 'ondblclick' in v.column.attrs:
                            ondblclick = v.column.attrs['ondblclick']
                            ids = re.findall('[0-9]+', ondblclick)
                            if len(ids) == 2:
                                url = urljoin(self.url, self.SOLUTION_URL_FORMAT_.format(*ids))
                                p['url'] = url
                                p['external_solution'] = True

                        *info, p['time'] = info
                        if info and info[0] == '(':
                            m = re.search('-([0-9]+)', info[1])
                            if m:
                                p['penalty_score'] = m.group(1)
                            info = info[3:]
                    if not problems:
                        continue

                    hack = row.pop('hack')
                    if hack:
                        row['hack'] = {'title': 'hacks'}
                        m = re.search(r'\+[0-9]+', hack)
                        row['hack']['successful'] = int(m.group(0)) if m else 0
                        m = re.search(r'\-[0-9]+', hack)
                        row['hack']['unsuccessful'] = -int(m.group(0)) if m else 0

                    handle = row['member']
                    if statistics and handle in statistics:
                        stat = statistics[handle]
                        for k in ('old_rating', 'rating_change', 'new_rating'):
                            if k in stat:
                                row[k] = stat[k]

                    results[handle] = row
                pbar.update()

        ret = {
            'url': standings_url,
            'problems': list(problems_infos.values()),
            'result': results,
            'options': {
                'fixed_fields': [('hack', 'Hack')],
            },
        }
        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        page = REQ.get(urljoin(resource.profile_url, Statistic.SETTINGS_URL_))
        form = REQ.form(action=r'login.php\?action=login')
        if form:
            data = {
                'username': conf.BESTCODER_AUTHORID,
                'password': conf.BESTCODER_PASSWORD,
                'remember': 'on',
            }
            page = REQ.submit_form(data=data, form=form)

        match = re.search('<select[^>]*id="country"[^>]*>.*?</select>', page, re.DOTALL)
        countries = dict(re.findall('<option[^>]*value="([0-9]+)"[^>]*>([^<]*)</option>', match.group(0)))

        @RateLimiter(max_calls=5, period=1)
        def fetch_user(user):
            n_attempts = 4
            url = resource.profile_url.format(account=user)
            page = REQ.get(url, n_attempts=n_attempts)

            info = {}

            matches = re.findall(r'<span[^>]*>([A-Z]+)</span>\s*<span[^>]*>([0-9]+)</span>', page)
            for k, v in matches:
                info[k.lower()] = int(v)

            match = re.search('<img[^>]*src="[^"]*country[^"]*/([0-9]+)[^"/]*"[^>]*alt="country"[^>]*>', page)
            if match:
                info['country'] = countries.get(match.group(1))

            match = re.search('<img[^>]*class="img-circle"[^>]*src="([^"]*getAvatar.php[^"]*)"[^>]*>', page)
            if match:
                info['avatar_url'] = urljoin(url, match.group(1))

            page = REQ.get(Statistic.USER_RATING_API_URL_.format(user), n_attempts=n_attempts)
            data = json.loads(page)
            ratings = {}
            old_rating = None
            for stat in data:
                rating = ratings.setdefault(stat['contestid'], collections.OrderedDict())
                new_rating = int(stat['rating'])
                if old_rating is not None:
                    rating['old_rating'] = old_rating
                    rating['rating_change'] = new_rating - old_rating
                rating['new_rating'] = new_rating
                old_rating = new_rating
                info['rating'] = new_rating

            if not ratings:
                info.pop('rating', None)

            return user, info, ratings

        with PoolExecutor(max_workers=8) as executor:
            for user, info, ratings in executor.map(fetch_user, users):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue
                info = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': ratings,
                        'by': 'key',
                    },
                }
                yield info

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')
        solution = REQ.get(problem['url'])
        ret = {'solution': solution}
        return ret
