#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import re
import json
import html
from datetime import datetime, timedelta
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from pprint import pprint

import tqdm
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://leetcode.com/contest/api/ranking/{key}/?pagination={{}}'
    RANKING_URL_FORMAT_ = '{url}/ranking'
    API_SUBMISSION_URL_FORMAT_ = 'https://leetcode{}.com/api/submissions/{}/'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @staticmethod
    def fetch_submission(submission):
        data_region = submission['data_region']
        data_region = '' if data_region == 'US' else f'-{data_region.lower()}'
        url = Statistic.API_SUBMISSION_URL_FORMAT_.format(data_region, submission['submission_id'])
        content = REQ.get(url)
        return submission, json.loads(content)

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url or self.RANKING_URL_FORMAT_.format(**self.__dict__)

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        url = api_ranking_url_format.format(1)
        content = REQ.get(url)
        data = json.loads(content)
        if not data:
            return {'result': {}, 'url': standings_url}
        n_page = (data['user_num'] - 1) // len(data['total_rank']) + 1

        problems_info = OrderedDict((
            (
                str(p['question_id']),
                {
                    'code': p['question_id'],
                    'short': f'Q{i}',
                    'name': p['title'],
                    'url': os.path.join(self.url, 'problems', p['title_slug']),
                    'full_score': p['credit'],
                }
            )
            for i, p in enumerate(data['questions'], start=1)
        ))

        def fetch_page(page):
            url = api_ranking_url_format.format(page + 1)
            content = REQ.get(url)
            return json.loads(content)

        result = {}
        stop = False
        timing_statistic_delta = None
        if users is None or users:
            if users:
                users = list(users)
            start_time = self.start_time.replace(tzinfo=None)
            with PoolExecutor(max_workers=8) as executor:
                solutions_for_get = []

                for data in tqdm.tqdm(
                    executor.map(fetch_page, range(n_page)),
                    total=n_page,
                    desc='parsing statistics paging',
                ):
                    if stop:
                        break
                    for row, submissions in zip(data['total_rank'], data['submissions']):
                        handle = row.pop('user_slug')
                        if users and handle not in users:
                            continue
                        row.pop('contest_id')
                        row.pop('global_ranking')

                        r = result.setdefault(handle, OrderedDict())
                        r['member'] = handle
                        r['place'] = row.pop('rank')
                        r['solving'] = row.pop('score')

                        name = row.pop('username')
                        if name != handle:
                            row['name'] = name

                        data_region = row.pop('data_region').lower()
                        r['info'] = {'profile_url': {'_data_region': '' if data_region == 'us' else f'-{data_region}'}}

                        country = None
                        for field in 'country_code', 'country_name':
                            country = country or row.pop(field, None)
                        if country:
                            r['country'] = country

                        problems_stats = (statistics or {}).get(handle, {}).get('problems', {})

                        solved = 0
                        problems = r.setdefault('problems', {})
                        for i, (k, s) in enumerate(submissions.items(), start=1):
                            short = problems_info[k]['short']
                            p = problems.setdefault(short, problems_stats.get(short, {}))
                            p['time'] = self.to_time(datetime.fromtimestamp(s['date']) - start_time)
                            if s['status'] == 10:
                                solved += 1
                                p['result'] = '+' + str(s['fail_count'] or '')
                            else:
                                p['result'] = f'-{s["fail_count"]}'
                            if 'submission_id' in s:
                                p['submission_id'] = s['submission_id']
                                p['external_solution'] = True
                                p['data_region'] = s['data_region']
                                if 'language' not in p:
                                    s['handle'] = handle
                                    solutions_for_get.append(s)

                        r['solved'] = {'solving': solved}
                        finish_time = datetime.fromtimestamp(row.pop('finish_time')) - start_time
                        r['penalty'] = self.to_time(finish_time)
                        r.update(row)
                        if statistics and handle in statistics:
                            stat = statistics[handle]
                            for k in ('rating_change', 'new_rating'):
                                if k in stat:
                                    r[k] = stat[k]
                        if users:
                            users.remove(handle)
                            if not users:
                                stop = True
                                break

                if statistics is not None and solutions_for_get:
                    if statistics:
                        for s, d in tqdm.tqdm(executor.map(Statistic.fetch_submission, solutions_for_get),
                                              total=len(solutions_for_get),
                                              desc='getting solutions'):
                            short = problems_info[str(s['question_id'])]['short']
                            result[s['handle']]['problems'][short].update({'language': d['lang']})
                    elif result:
                        timing_statistic_delta = timedelta(minutes=15)

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }
        if timing_statistic_delta:
            standings['timing_statistic_delta'] = timing_statistic_delta
        return standings

    @staticmethod
    def get_source_code(contest, problem):
        _, data = Statistic.fetch_submission(problem)
        return {'solution': data['code']}

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def is_chine(account):
            return '-cn' in account.info.get('profile_url', {}).get('_data_region', '')

        @RateLimiter(max_calls=1, period=2)
        def fetch_profle_page(account):
            page = False
            try:
                if is_chine(account):
                    ret = {}
                    page = REQ.get(
                        'https://leetcode.com/graphql',
                        post=b'{"variables":{},"query":"{allContests{titleSlug}}"}',
                        content_type='application/json',
                    )
                    ret['contests'] = json.loads(page)['data']

                    page = REQ.get(
                        'https://leetcode-cn.com/graphql',
                        post=b'''
                        {"operationName":"userPublicProfile","variables":{"userSlug":"''' + account.key.encode() + b'''"},"query":"query userPublicProfile($userSlug: String!) { userProfilePublicProfile(userSlug: $userSlug) { username profile { userSlug realName contestCount ranking { currentLocalRanking currentGlobalRanking currentRating ratingProgress totalLocalUsers totalGlobalUsers } } }}"}''',  # noqa
                        content_type='application/json',
                    )
                    ret['profile'] = json.loads(page)['data']
                    page = ret
                else:
                    url = resource.profile_url.format(**account.dict_with_info())
                    page = REQ.get(url)
            except FailOnGetResponse as e:
                arg = e.args[0]
                if not hasattr(arg, 'code') or arg.code == 404:
                    page = None
                else:
                    page = False
            return account, page

        with PoolExecutor(max_workers=2) as executor:
            for account, page in executor.map(fetch_profle_page, accounts):
                if pbar:
                    pbar.update()

                if not page:
                    if page is None:
                        yield {'info': None}
                    yield {'skip': True}
                    continue

                info = {}
                contest_addition_update_by = None
                ratings, titles = [], []
                if is_chine(account):
                    contests = [c['titleSlug'] for c in page['contests']['allContests']]
                    info = page['profile']['userProfilePublicProfile']
                    if info is None:
                        yield {'info': None}
                        continue
                    info.update(info.pop('profile', {}) or {})
                    info.update(info.pop('ranking', {}) or {})
                    ratings = info.pop('ratingProgress', []) or []
                    contests = contests[len(contests) - len(ratings):]
                    titles = list(reversed(contests))
                else:
                    matches = re.finditer(
                        r'''
                        <li[^>]*>\s*<span[^>]*>(?P<value>[^<]*)</span>\s*
                        <i[^>]*>[^<]*</i>(?P<key>[^<]*)
                        ''',
                        page,
                        re.VERBOSE
                    )

                    for match in matches:
                        key = html.unescape(match.group('key')).strip().replace(' ', '_').lower()
                        value = html.unescape(match.group('value')).strip()
                        if value.isdigit():
                            value = int(value)
                        info[key] = value

                    contest_addition_update = {}
                    contest_addition_update_by = None
                    match = re.search(r'ng-init="pc.init\((?P<data>.*?)\)"\s*ng-cloak>', page, re.DOTALL)
                    if match:
                        data = html.unescape(match.group('data').replace("'", '"'))
                        data = json.loads(f'[{data}]')
                        filtered_data = [d for d in reversed(data) if d and isinstance(d, list)]
                        if len(filtered_data) >= 2:
                            titles, ratings, *_ = filtered_data
                            if ratings:
                                ratings = [v for v, _ in ratings]
                                contest_addition_update_by = 'title'

                contest_addition_update = {}
                prev_rating = None
                last_rating = None
                if ratings and titles:
                    for rating, title in zip(ratings, titles):
                        if prev_rating != rating and (prev_rating is not None or rating != 1500):
                            int_rating = int(rating)
                            update = contest_addition_update.setdefault(title, OrderedDict())
                            update['rating_change'] = int_rating - last_rating if last_rating is not None else None
                            update['new_rating'] = int_rating
                            info['rating'] = int_rating
                            last_rating = int_rating
                        prev_rating = rating

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': contest_addition_update_by,
                        'clear_rating_change': True,
                    },
                }
                yield ret


if __name__ == "__main__":
    statictic = Statistic(
        name='Biweekly Contest 18',
        url='https://leetcode.com/contest/biweekly-contest-18/',
        key='biweekly-contest-18',
        start_time=datetime.now(),
        standings_url=None,
    )
    pprint(next(iter(statictic.get_standings()['result'].values())))
