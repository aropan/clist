#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ, BaseModule
import conf

from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import json
import time


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://api.hackerearth.com/challenges/v1/leaderboard/'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):
        api_ranking_url = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)

        def fetch_page(page_index):
            time.sleep(1)
            payload = {
                'client_id': conf.HACKEREARTH_CLIENT_ID,
                'client_secret': conf.HACKEREARTH_CLIENT_SECRET,
                'challenge_slug': self.key,
                'page_index': page_index + 1,
            }
            content = REQ.get(api_ranking_url, post=json.dumps(payload).encode('utf-8'), time_out=30)
            return json.loads(content)

        data = fetch_page(0)
        max_page_index = data['max_page_index']

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_page, range(max_page_index)):
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
                    break
        print(self.name, self.url, len(result))
        standings = {
            'result': result,
            'url': self.url + 'leaderboard/',
        }
        return standings


if __name__ == "__main__":
    from pprint import pprint

    statictic = Statistic(
        name='HourStorm #11',
        url='https://www.hackerearth.com/challenges/competitive/hourstorm-11/',
        key='hourstorm-11',
    )
    pprint(statictic.get_standings())
