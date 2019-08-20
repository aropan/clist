#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
import json
import time
import urllib.parse

import tqdm

from common import REQ, LOG, BaseModule, parsed_table
from excepts import ExceptionParseStandings
import conf


class Statistic(BaseModule):
    RANKING_URL_FORMAT_ = 'https://www.hackerearth.com/AJAX/feed/newsfeed/icpc-leaderboard/event/{event_id}/{page}/'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):
        standings_url = urllib.parse.urljoin(self.url, 'leaderboard/')

        page = REQ.get(standings_url)
        match = re.search('<div[^>]*class="event-id hidden"[^>]*>(?P<id>[0-9]*)</div>', page)
        if not match:
            return ExceptionParseStandings('Not found event id')

        event_id = match.group('id')

        quit = False

        def fetch_page(page_index):
            url = self.RANKING_URL_FORMAT_.format(event_id=event_id, page=page_index)
            page = REQ.get(url)
            page = re.sub('<!--.*?-->', '', page)
            with open('page.heml', 'w') as fo:
                fo.write(page)
            table = parsed_table.ParsedTable(page)
            for r in table:
                for k, v in r.items():
                    print(k, v)
                break

        fetch_page(1)

        exit(0)

        data = fetch_page(0)
        max_page_index = data['max_page_index']

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in tqdm.tqdm(executor.map(fetch_page, range(max_page_index)), total=max_page_index):
                if not data:
                    continue
                n_skip = 0
                n_row = 0
                for row in data['leaderboard']:
                    n_row += 1
                    if not row['score']:
                        n_skip += 1
                        continue
                    handle = row.pop('username')

                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['place'] = row.pop('rank')
                    r['solving'] = row.pop('score')
                    r['solved'] = {'solving': row.pop('problems_solved')}
                    r['penalty'] = row.pop('time_taken')
                    r.update(row)
                if n_row == n_skip:
                    quit = True
                    break

        standings = {
            'result': result,
            'url': self.url + 'leaderboard/',
        }
        return standings


if __name__ == "__main__":
    from pprint import pprint

    statictic = Statistic(
        name='HourStorm #11',
        url='https://www.hackerearth.com/challenges/competitive/hourstorm-14/',
        key='deep-learning-challenge-1',
    )
    pprint(statictic.get_standings())
