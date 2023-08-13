#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack
from datetime import timedelta
from pprint import pprint
from urllib.parse import quote_plus, urlparse

import arrow
import tqdm
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    API_RANKING_URL_FORMATS_ = {
        'v2': '{resource}/api/v2/contest/{key}',
        'v1': '{resource}/api/contest/info/{key}',
    }
    PROBLEM_URL_ = '{resource}/problem/{code}'
    FETCH_USER_INFO_URL_ = '{resource}/api/user/info/{user}'
    API_USER_URL_ = '{resource}/api/v2/user/{user}'

    def get_standings(self, users=None, statistics=None):
        api_ranking_url_version = self.resource.info.get('statistics', {}).get('api_ranking_url_version', 'v2')
        resource = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(self.url))
        infos = self.__dict__
        infos['resource'] = resource
        url = self.API_RANKING_URL_FORMATS_[api_ranking_url_version].format(**infos)
        try:
            time.sleep(1)
            page = REQ.get(url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise ExceptionParseStandings('not found api ranking url')

        data = json.loads(page)
        if 'data' in data and 'object' in data['data']:
            data = data['data']['object']

        problems_info = []
        for idx, p in enumerate(data.pop('problems'), start=1):
            info = {
                'short': p.get('label', str(idx)),
                'name': p['name'],
                'code': p['code'],
            }
            info['url'] = self.PROBLEM_URL_.format(resource=resource, **info)
            if p.get('points'):
                info['full_score'] = p['points']
            problems_info.append(info)

        result = {}
        prev = None
        skip = 0
        handles_to_get_new_rating = []
        has_rated = data.get('is_rated', True) and data.get('has_rating', True)
        has_rating = False

        rankings = data.pop('rankings')
        for r in rankings:
            for src, dst in (
                ('points', 'score'),
                ('cumtime', 'cumulative_time'),
            ):
                if src in r:
                    r[dst] = r.pop(src)
        rankings = sorted(rankings, key=lambda x: (-x['score'], x['cumulative_time']))

        fields_types = {}
        hidden_fields = set()
        for index, r in enumerate(rankings, start=1):
            solutions = r.pop('solutions')
            if not any(solutions) and not r.get('new_rating'):
                skip += 1
                continue
            handle = r.pop('user')
            row = result.setdefault(handle, collections.OrderedDict())

            row['member'] = handle
            row['solving'] = r.pop('score')
            cumulative_time = r.pop('cumulative_time')
            if cumulative_time:
                row['penalty'] = self.to_time(cumulative_time)

            curr = (row['solving'], cumulative_time)
            if curr != prev:
                prev = curr
                rank = index - skip
            row['place'] = rank

            solved = 0
            problems = row.setdefault('problems', {})
            if solutions and not problems_info:
                problems_info = [{'short': str(idx + 1)} for idx in range(len(solutions))]
            for prob, sol in zip(problems_info, solutions):
                if not sol:
                    continue
                p = problems.setdefault(prob['short'], {})
                if sol['points'] > 0 and prob.get('full_score'):
                    p['partial'] = prob['full_score'] > sol['points']
                p['result'] = sol.pop('points')
                t = sol.pop('time')
                if t:
                    p['time'] = self.to_time(t)
                if p['result'] > 0 and not p.get('partial', False):
                    solved += 1

            r.pop('is_disqualified', None)
            r.pop('tiebreaker', None)

            row['old_rating'] = r.pop('old_rating', None)
            new_rating = r.pop('new_rating', None)
            if has_rated:
                row['rating_change'] = None
                row['new_rating'] = new_rating

            for k, v in r.items():
                hidden_fields.add(k)
                if k.endswith('_time'):
                    r[k] = arrow.get(v).timestamp()
                    fields_types.setdefault(k, ['time'])

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

                @RateLimiter(max_calls=1, period=2)
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

        standings_url = self.url.rstrip('/') + '/ranking/' if result else self.standings_url

        standings = {
            'result': result,
            'url': standings_url,
            'problems': problems_info,
            'fields_types': fields_types,
            'hidden_fields': list(hidden_fields),
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        host = '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(resource.url))

        @RateLimiter(max_calls=1, period=2)
        def fetch_profile(user, account):
            url = Statistic.API_USER_URL_.format(resource=host, user=quote_plus(user))

            try:
                data = REQ.get(url)
                data = json.loads(data)
                data = data['data']['object']
                data.pop('solved_problems', None)
                data.pop('contests', None)

                url = resource.profile_url.format(**account.dict_with_info())
                page = REQ.get(url)
                match = re.search(r'<div[^>]*class="content-description"[^>]*>\s*<h4>[^<]*</h4>\s*<p>(?P<value>[^<]*)</p>', page)  # noqa
                if match:
                    data['description'] = html.unescape(match.group('value'))
            except FailOnGetResponse:
                return False

            return data

        with PoolExecutor(max_workers=8) as executor:
            for info in executor.map(fetch_profile, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True, 'delta': timedelta(days=365)}
                    continue
                info = {'info': info}
                yield info


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
