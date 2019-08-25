#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
import urllib.parse
from time import sleep
from collections import OrderedDict

import tqdm

from common import REQ, LOG, BaseModule, parsed_table, FailOnGetResponse
from excepts import ExceptionParseStandings


class Statistic(BaseModule):
    RANKING_URL_FORMAT_ = 'https://www.hackerearth.com/AJAX/feed/newsfeed/icpc-leaderboard/event/{event_id}/{page}/'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @staticmethod
    def _get(url):
        attempt = 0
        while True:
            attempt += 1
            try:
                return REQ.get(url)
            except FailOnGetResponse as e:
                LOG.error(str(e))
                if attempt == 7 or e.args[0].code != 500:
                    raise ExceptionParseStandings(e)
                sleep(2 ** attempt)

    def get_standings(self, users=None):
        standings_url = urllib.parse.urljoin(self.url, 'leaderboard/')

        try:
            page = self._get(standings_url)
        except Exception as e:
            raise ExceptionParseStandings(e)

        match = re.search('<div[^>]*class="event-id hidden"[^>]*>(?P<id>[0-9]*)</div>', page)
        if not match:
            return ExceptionParseStandings('Not found event id')

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
                    problems_info[short] = {
                        'short': short,
                        'name': col.attrs['title'],
                        'full_score': int(re.sub(r'[\(\)]', '', full_score)),
                    }

            for row in table:
                r = {}
                r['solved'] = {'solving': 0}
                for k, v in row.items():
                    f = k.lower()
                    if 'developers' in f or 'view only in network' in f:
                        rank, name = v.value.split(' ', 1)
                        r['place'] = int(rank.strip('.'))
                        name, member = name.rsplit(' ', 1)
                        r['name'] = name
                        r['member'] = member
                    elif 'балл' in f or 'score' in f or 'problems solved' in f:
                        r['solving'] = float(v.value.split()[0])
                    elif 'total time' in f or 'hh:mm:ss' in f:
                        r['penalty'] = v.value.strip()
                    elif re.match('^p[0-9]+', f):
                        short = k.split()[0]
                        if v.value in ['N/A', 'Недоступно']:
                            continue
                        result, penalty = v.value.split()
                        result = float(result)
                        p = r.setdefault('problems', {}).setdefault(short, {})
                        p['result'] = result
                        p['penalty'] = penalty
                        if problems_info[short]['full_score'] > result + 1e-9:
                            p['partial'] = True
                        else:
                            r['solved']['solving'] += 1
                if r['solving'] < 1e-9:
                    continue

                results[r['member']] = r

            return page, problems_info

        page, problems_info = fetch_page(1)
        pages = re.findall('<a[^>]*href="[^"]*/page/([0-9]+)/?"', page)
        max_page_index = int(pages[-1]) if pages else 1

        with PoolExecutor(max_workers=8) as executor:
            for _ in tqdm.tqdm(executor.map(fetch_page, range(2, max_page_index + 1)), total=max_page_index - 1):
                pass

        standings = {
            'result': results,
            'problems': list(problems_info.values()),
            'url': standings_url,
        }
        return standings


if __name__ == "__main__":
    import sys
    import os
    from pprint import pprint

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from clist.models import Contest

    from django.utils import timezone

    contests = Contest.objects \
        .filter(host='hackerearth.com', end_time__lt=timezone.now() - timezone.timedelta(days=2)) \
        .order_by('-start_time') \

    for contest in contests[:10]:
        try:
            statistic = Statistic(
                name=contest.title,
                url=contest.url,
                key=contest.key,
                standings_url=contest.standings_url,
                start_time=contest.start_time,
            )
            s = statistic.get_standings()
            pprint(s)
            s.pop('result')
            pprint(s)
        except ExceptionParseStandings:
            continue
