#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import json
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from time import sleep
from collections import OrderedDict
from pprint import pprint
from threading import Lock

import tqdm
from first import first

from ranking.management.modules.common import REQ, BaseModule, parsed_table, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.management.modules import conf


class Statistic(BaseModule):
    RANKING_URL_FORMAT_ = 'https://www.hackerearth.com/AJAX/feed/newsfeed/icpc-leaderboard/event/{event_id}/{page}/'
    RATING_URL_FORMAT_ = 'https://www.hackerearth.com/ratings/AJAX/rating-graph/{account}/'
    LOGIN_URL_ = 'https://www.hackerearth.com/en-us/login/'
    LOGGED_IN = False

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @staticmethod
    def _get(url, lock=Lock()):
        attempt = 0
        while True:
            attempt += 1
            try:
                page = REQ.get(url)
                if 'id="id_login"' in page and 'id="id_password"' in page:
                    with lock:
                        if not Statistic.LOGGED_IN:
                            page = REQ.get(Statistic.LOGIN_URL_)
                            page = REQ.submit_form(
                                {
                                    'login': conf.HACKEREARTH_USERNAME,
                                    'password': conf.HACKEREARTH_PASSWORD,
                                    'signin': 'Log In',
                                },
                                limit=0,
                            )
                            Statistic.LOGGED_IN = True
                    page = REQ.get(url)
                return page
                # if 'AJAX' in url:
                #     headers = {'x-requested-with': 'XMLHttpRequest'}
                #     csrftoken = REQ.get_cookie('csrftoken')
                #     if csrftoken:
                #         headers['x-csrftoken'] = csrftoken
                # else:
                #     headers = {}
                # return REQ.get(url, headers=headers)
            except FailOnGetResponse as e:
                if attempt == 7 or getattr(e.args[0], 'code', None) != 500:
                    raise ExceptionParseStandings(e.args[0])
                sleep(2 ** attempt)

    def get_standings(self, users=None, statistics=None, fixed_rank=None):
        standings_url = urllib.parse.urljoin(self.url, 'leaderboard/')

        try:
            page = self._get(self.url)
        except ExceptionParseStandings as e:
            if getattr(e.args[0], 'code', None) == 404:
                return {'action': 'delete'}

        try:
            page = self._get(standings_url)
        except ExceptionParseStandings as e:
            raise ExceptionParseStandings(e.args[0])

        match = re.search('<div[^>]*class="event-id hidden"[^>]*>(?P<id>[0-9]*)</div>', page)
        if not match:
            raise ExceptionParseStandings('Not found event id')

        event_id = match.group('id')

        results = {}

        def fetch_page(page_index):
            nonlocal results

            url = self.RANKING_URL_FORMAT_.format(event_id=event_id, page=page_index)
            page = self._get(url)
            page = re.sub('<!--.*?-->', '', page)

            table = parsed_table.ParsedTable(page)

            problems_info = OrderedDict()
            for col in table.header.columns:
                if col.attrs.get('class') == 'tool-tip align-center':
                    short = col.value.split()[0]
                    _, full_score = col.value.rsplit(' ', 1)
                    info = {
                        'short': short,
                        'name': col.attrs['title'],
                        'full_score': int(re.sub(r'[\(\)]', '', full_score)),
                    }
                    url = first(col.node.xpath('.//a/@href'))
                    if url:
                        info['url'] = urllib.parse.urljoin(self.url, url)
                        info['code'] = url.strip('/').split('/')[-1]
                    problems_info[short] = info

            for row in table:
                r = {}
                r['solved'] = {'solving': 0}
                for k, v in row.items():
                    f = k.lower()
                    if ('developers' in f or 'view only in network' in f or 'team' in f) and 'place' not in r:
                        disq = v.column.node.xpath('.//*[@title="Disqualified from the challenge."]')
                        if disq:
                            r = {}
                            break
                        rank, name = v.value.split(' ', 1)
                        r['place'] = int(rank.strip('.'))

                        members_teams = v.column.node.xpath('.//a[contains(@ajax, "members-team")]/@ajax')
                        if members_teams:
                            r['members'] = []
                            url = members_teams[0]
                            r['team_id'] = re.search('(?P<team_id>[0-9]+)/?$', url).group('team_id')
                            members_page = self._get(url)
                            members_page = json.loads(members_page)['data']
                            members_table = parsed_table.ParsedTable(members_page)
                            for member_row in members_table:
                                _, member = member_row['Developer'].value.strip().rsplit(' ', 1)
                                r['members'].append(member)
                            r['name'] = f'{name}: {", ".join(r["members"])}'
                        else:
                            if ' ' in name:
                                name, member = name.rsplit(' ', 1)
                            else:
                                member = name
                            r['name'] = name
                            r['members'] = [member]
                    elif ('балл' in f or 'score' in f or 'problems solved' in f) and 'solving' not in r:
                        r['solving'] = float(v.value.split()[0])
                    elif 'total time' in f or 'hh:mm:ss' in f:
                        r['penalty'] = v.value.strip()
                    elif re.match('^p[0-9]+', f):
                        short = k.split()[0]
                        if v.value in ['N/A', 'Недоступно']:
                            continue
                        p = r.setdefault('problems', {}).setdefault(short, {})

                        if ' ' in v.value:
                            result, penalty, *_ = v.value.split()
                            p['time'] = penalty
                        else:
                            result = v.value

                        result = float(result)
                        p['result'] = result
                        if result > 1e-9:
                            if problems_info[short]['full_score'] > result + 1e-9:
                                p['partial'] = True
                            else:
                                r['solved']['solving'] += 1
                            if 'background-color: #d5e8d2' in v.column.attrs.get('style', ''):
                                p['first_ac'] = True
                if not r or r.get('solving', 0) < 1e-9 and 'problems' not in r:
                    continue
                if fixed_rank is not None and fixed_rank != r['place']:
                    continue

                members = r.pop('members')
                for member in members:
                    if users and member not in users:
                        continue
                    r['member'] = member
                    results[member] = dict(r)

            return page, problems_info

        if fixed_rank is not None:
            per_page = 50
            page_index = (fixed_rank - 1) // per_page + 1
            _, problems_info = fetch_page(page_index)
            if page_index > 1 and fixed_rank % per_page == 1:
                fetch_page(page_index - 1)
            if fixed_rank % per_page == 0:
                fetch_page(page_index + 1)
        else:
            page, problems_info = fetch_page(1)
            pages = re.findall('<a[^>]*href="[^"]*/page/([0-9]+)/?"', page)
            max_page_index = int(pages[-1]) if pages else 1

            if users is None or users:
                with PoolExecutor(max_workers=8) as executor:
                    for _ in tqdm.tqdm(executor.map(fetch_page, range(2, max_page_index + 1)),
                                       total=max_page_index - 1):
                        pass

        standings = {
            'result': results,
            'problems': list(problems_info.values()),
            'url': standings_url,
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_account(account):
            ret = {}
            info = ret.setdefault('info', {})

            ts = (datetime.now() - timedelta(days=30)).timestamp()
            if 'country_ts' not in account.info or account.info['country_ts'] < ts:
                try:
                    url = resource.profile_url.format(**account.dict_with_info())
                    page = Statistic._get(url)
                except ExceptionParseStandings as e:
                    arg = e.args[0]
                    if not hasattr(arg, 'code') or arg.code == 404:
                        for stat in account.statistics_set.order_by('-contest__end_time')[:3]:
                            if stat.place is None:
                                continue
                            if stat.solving < 1e-9:
                                continue
                            try:
                                module = Statistic(contest=stat.contest)
                                standings = module.get_standings(fixed_rank=stat.place_as_int)
                            except Exception:
                                continue
                            results = standings.get('result', {})
                            if len(results) != 1:
                                continue
                            member, result = list(results.items())[0]
                            if (
                                not re.search('[1-9]', result.get('penalty', ''))
                                or result['penalty'] != stat.addition.get('penalty')
                            ):
                                continue
                            if abs(stat.solving - result.get('solving', 0)) > 1e-9:
                                continue

                            if member == account.key:
                                return account, {'info': None}

                            return account, {'rename': member, 'info': {}}
                        return account, {'info': {}}

                match = re.search(r'''
                    <div[^>]*class="[^"]*track-current-location[^"]*"[^>]*>
                    [^<]*<i[^>]*>[^<]*</[^>]*>
                    [^<]*<span[^>]*>[^<]*,\s*(?P<country>[^,<]+)\s*</[^>]*>
                ''', page, re.VERBOSE)
                if match:
                    info['country'] = match.group('country')
                info['country_ts'] = datetime.now().timestamp()

            url = Statistic.RATING_URL_FORMAT_.format(account=account.key)
            page = Statistic._get(url)
            matches = re.search(r'var[^=]*=\s*(?P<data>.*);$', page, re.M)
            data = json.loads(matches.group('data'))
            contest_addition_update = ret.setdefault('contest_addition_update', {})
            for contest in data:
                key = re.search(r'/(?P<key>[^/]+)/$', contest['event_url']).group('key')
                addition_update = contest_addition_update.setdefault(key, OrderedDict())
                for src, dst in (
                    ('old_rating', 'old_rating'),
                    ('rating_change', 'rating_change'),
                    ('rating', 'new_rating'),
                ):
                    if src in contest:
                        addition_update[dst] = int(contest[src])
                if 'rating' in contest:
                    info['rating'] = int(contest['rating'])

            return account, ret

        with PoolExecutor(max_workers=8) as executor:
            for account, data in executor.map(fetch_account, accounts):
                if pbar:
                    pbar.update()
                yield data


if __name__ == "__main__":
    import sys
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from clist.models import Contest

    from django.utils import timezone

    contests = Contest.objects \
        .filter(title="ACM ICPC Practice Contest") \
        .filter(host='hackerearth.com', end_time__lt=timezone.now() - timezone.timedelta(days=2)) \
        .order_by('-start_time') \

    for contest in contests[:1]:
        try:
            statistic = Statistic(
                name=contest.title,
                url=contest.url,
                key=contest.key,
                standings_url=contest.standings_url,
                start_time=contest.start_time,
            )
            s = statistic.get_standings()
            pprint(s.pop('result'))
            pprint(s)
        except ExceptionParseStandings:
            continue
