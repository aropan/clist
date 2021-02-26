#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import time
import collections
from urllib.parse import quote_plus, urlparse
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack
from ratelimiter import RateLimiter

import tqdm

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = '{resource}/api/contest/info/{key}'
    PROBLEM_URL_ = '{resource}/problem/{short}'
    FETCH_USER_INFO_URL_ = '{resource}/api/user/info/{user}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        resource = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(self.url))

        infos = self.__dict__
        infos['resource'] = resource
        url = self.API_RANKING_URL_FORMAT_.format(**infos)
        try:
            time.sleep(1)
            page = REQ.get(url)
        except Exception as e:
            return {'action': 'delete'} if e.args[0].code == 404 else {}

        data = json.loads(page)

        problems_info = []
        for p in data['problems']:
            info = {
                'short': p['code'],
                'name': p['name'],
            }
            info['url'] = self.PROBLEM_URL_.format(resource=resource, **info)
            if p.get('points'):
                info['full_score'] = p['points']
            problems_info.append(info)

        result = {}
        prev = None
        handles_to_get_new_rating = []
        has_rated = data.get('is_rated', True) or data.get('has_rating', True)
        has_rating = False
        rankings = sorted(data['rankings'], key=lambda x: (-x['points'], x['cumtime']))
        for index, r in enumerate(rankings, start=1):
            solutions = r.pop('solutions')
            if not any(solutions):
                continue
            handle = r.pop('user')
            row = result.setdefault(handle, collections.OrderedDict())

            row['member'] = handle
            row['solving'] = r.pop('points')
            cumtime = r.pop('cumtime')
            if cumtime:
                row['penalty'] = self.to_time(cumtime)

            curr = (row['solving'], cumtime)
            if curr != prev:
                prev = curr
                rank = index
            row['place'] = rank

            solved = 0
            problems = row.setdefault('problems', {})
            for prob, sol in zip(data['problems'], solutions):
                if not sol:
                    continue
                p = problems.setdefault(prob['code'], {})
                if sol['points'] > 0 and prob.get('partial'):
                    p['partial'] = prob['points'] - sol['points'] > 1e-7
                    if not p['partial']:
                        solved += 1
                p['result'] = sol.pop('points')
                t = sol.pop('time')
                if t:
                    p['time'] = self.to_time(t)

            r.pop('is_disqualified', None)
            r.pop('tiebreaker', None)

            row['old_rating'] = r.pop('old_rating', None)
            new_rating = r.pop('new_rating', None)
            if has_rated:
                row['rating_change'] = None
                row['new_rating'] = new_rating

            row.update({k: v for k, v in r.items() if k not in row})

            row['solved'] = {'solving': solved}

            if has_rated:
                if row.get('new_rating') is not None:
                    has_rating = True
                elif statistics is None or 'new_rating' not in statistics.get(handle, {}):
                    handles_to_get_new_rating.append(handle)
                else:
                    row['old_rating'] = statistics[handle].get('old_rating')
                    row['new_rating'] = statistics[handle]['new_rating']

        if has_rated and not has_rating and handles_to_get_new_rating:
            with ExitStack() as stack:
                executor = stack.enter_context(PoolExecutor(max_workers=8))
                pbar = stack.enter_context(tqdm.tqdm(total=len(handles_to_get_new_rating), desc='getting new rankings'))

                @RateLimiter(max_calls=1, period=1)
                def fetch_data(handle):
                    url = self.FETCH_USER_INFO_URL_.format(resource=resource, user=quote_plus(handle))
                    page = REQ.get(url)
                    data = json.loads(page)
                    return handle, data

                for handle, data in executor.map(fetch_data, handles_to_get_new_rating):
                    rating = data.get('contests', {}).get('current_rating')
                    if rating:
                        result[handle].setdefault('info', {})['rating'] = rating

                    contest_addition_update = {}
                    for key, contest in data['contests']['history'].items():
                        rating = contest.get('rating')
                        if not rating:
                            continue
                        if key == self.key:
                            result[handle]['new_rating'] = rating
                        else:
                            contest_addition_update[key] = collections.OrderedDict((('new_rating', rating), ))
                    result[handle]['contest_addition_update'] = contest_addition_update
                    pbar.update()

        standings_url = hasattr(self, 'standings_url') and self.standings_url or self.url.rstrip('/') + '/ranking/'
        standings = {
            'result': result,
            'url': standings_url,
            'problems': problems_info,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='42',
        url='https://dmoj.ca/contest/dmopc18c2/',
        key='dmopc18c2',
    )
    pprint(statictic.get_result('ayyyyyyyyyyyyyLMAO'))

    statictic = Statistic(
        name="Mock CCO '19 Contest 2, Day 1",
        url='http://www.dmoj.ca/contest/mcco19c2d1',
        key='mcco19c2d1',
    )
    pprint(statictic.get_result('GSmerch', 'georgehtliu'))

    statictic = Statistic(
        name='Deadly Serious Contest Day 1',
        url='http://www.dmoj.ca/contest/dsc19d1',
        key='dsc19d1',
    )
    pprint(statictic.get_result('scanhex', 'wleung_bvg'))

    statictic = Statistic(
        name="Mock CCO '19 Contest 2, Day 1",
        url='https://dmoj.ca/contest/tle16',
        key='tle16',
    )
    pprint(statictic.get_standings())
