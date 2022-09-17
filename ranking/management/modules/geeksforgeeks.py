#!/usr/bin/env python3

import json
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import dateutil.parser
from ratelimiter import RateLimiter

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        page = REQ.get('https://auth.geeksforgeeks.org/')
        form = REQ.form(page=page, action=None, fid='Login')
        if form:
            REQ.get('https://auth.geeksforgeeks.org/setLoginToken.php')
            page = REQ.submit_form(
                url='https://auth.geeksforgeeks.org/auth.php',
                data={
                    'user': conf.GEEKSFORGEEKS_USERNAME,
                    'pass': conf.GEEKSFORGEEKS_PASSWORD,
                },
                form=form,
            )

    def get_standings(self, users=None, statistics=None):

        result = {}

        @RateLimiter(max_calls=10, period=2)
        def fetch_and_process_page(page):
            url = f'https://practiceapi.geeksforgeeks.org/api/v1/contest/{self.key}/leaderboard/?page={page + 1}&type=current'  # noqa
            page = REQ.get(url)
            data = json.loads(page)

            for row in data['results']['ranks_list']:
                handle = row.pop('profile_link').rstrip('/').rsplit('/', 1)[-1]
                r = result.setdefault(handle, OrderedDict())
                name = row.pop('handle')
                if name != handle:
                    r['name'] = name
                r['member'] = handle
                r['place'] = row.pop('rank')
                r['solving'] = row.pop('score')
                last_correct_submission = row.get('last_correct_submission')
                if last_correct_submission:
                    time = dateutil.parser.parse(last_correct_submission + '+05:30')
                    delta = time - self.start_time
                    r['time'] = self.to_time(delta)
                for k, v in list(row.items()):
                    if k.endswith('_score'):
                        r[k] = row.pop(k)

            return data

        try:
            data = fetch_and_process_page(0)
        except FailOnGetResponse as e:
            if e.code == 403:
                raise ExceptionParseStandings(str(e))
            raise e
        total = data['results']['rows_count']
        per_page = len(data['results']['ranks_list'])
        if not total or not per_page:
            raise ExceptionParseStandings('empty standings')
        n_pages = (total + per_page - 1) // per_page

        with PoolExecutor(max_workers=8) as executor:
            executor.map(fetch_and_process_page, range(1, n_pages))

        ret = {
            'url': os.path.join(self.url, 'leaderboard'),
            'result': result,
        }
        return ret
