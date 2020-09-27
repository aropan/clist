#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import json
import yaml
import html
import time
from functools import lru_cache
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from pprint import pprint

import tqdm
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules import conf


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://leetcode.com/contest/api/ranking/{key}/?pagination={{}}&region=global'
    RANKING_URL_FORMAT_ = '{url}/ranking'
    API_SUBMISSION_URL_FORMAT_ = 'https://leetcode{}.com/api/submissions/{}/'
    STATE_FILE = os.path.join(os.path.dirname(__file__), '.leetcode.yaml')

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @classmethod
    def _get(self, *args, **kwargs):
        if not getattr(self, '_authorized', None) and getattr(conf, 'LEETCODE_COOKIES', False):
            for kw in conf.LEETCODE_COOKIES:
                REQ.add_cookie(**kw)
            setattr(self, '_authorized', True)
        return REQ.get(*args, **kwargs)

    @staticmethod
    def fetch_submission(submission):
        data_region = submission['data_region']
        data_region = '' if data_region == 'US' else f'-{data_region.lower()}'
        url = Statistic.API_SUBMISSION_URL_FORMAT_.format(data_region, submission['submission_id'])
        try:
            content = REQ.get(url)
            content = json.loads(content)
        except FailOnGetResponse:
            content = None

        return submission, content

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url or self.RANKING_URL_FORMAT_.format(**self.__dict__)

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        url = api_ranking_url_format.format(1)
        content = Statistic._get(url)
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

        def update_problem_info(info):
            slug = info['url'].strip('/').rsplit('/', 1)[-1]
            params = {
                'operationName': 'questionData',
                'variables': {'titleSlug': slug},
                'query': 'query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { questionId difficulty contributors { profileUrl } topicTags { name } hints } }', # noqa
            }
            page = REQ.get(
                'https://leetcode.com/graphql',
                content_type='application/json',
                post=json.dumps(params).encode('utf-8'),
            )
            question = json.loads(page)['data']['question']
            info['tags'] = [t['name'].lower() for t in question['topicTags']]
            info['writers'] = [
                re.search('/(?P<username>[^/]*)/?$', c['profileUrl']).group('username')
                for c in question['contributors']
            ]
            if not info['writers']:
                info['writers'] = ['leetcode']
            info['difficulty'] = question['difficulty'].lower()
            info['hints'] = question['hints']
            return info

        writers = defaultdict(int)
        with PoolExecutor(max_workers=8) as executor:
            for problem_info in executor.map(update_problem_info, problems_info.values()):
                for w in problem_info['writers']:
                    writers[w] += 1

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
                        if users and handle not in users or handle in result:
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
                            if d is None:
                                continue
                            short = problems_info[str(s['question_id'])]['short']
                            result[s['handle']]['problems'][short].update({'language': d['lang']})
                    elif result:
                        timing_statistic_delta = timedelta(minutes=15)

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }
        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers
        if timing_statistic_delta:
            standings['timing_statistic_delta'] = timing_statistic_delta
        return standings

    @staticmethod
    def get_source_code(contest, problem):
        _, data = Statistic.fetch_submission(problem)
        return {'solution': data['code']}

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        rate_limiter = RateLimiter(max_calls=1, period=4)
        code_errors = defaultdict(int)

        def is_chine(account):
            profile_url = account.info.setdefault('profile_url', {})
            if profile_url.get('_data_region') is None:
                profile_url['_data_region'] = ''
                account.save()
            return '-cn' in profile_url['_data_region']

        @lru_cache()
        def get_all_contests():
            page = Statistic._get(
                'https://leetcode.com/graphql',
                post=b'{"variables":{},"query":"{allContests{titleSlug}}"}',
                content_type='application/json',
            )
            return json.loads(page)['data']

        def fetch_profile_data(account):
            nonlocal stop
            nonlocal global_ranking_users
            nonlocal rate_limiter
            nonlocal n_chinese_accounts_parse

            if not is_chine(account):
                key = (account.info['profile_url']['_data_region'], account.key)
                if key in global_ranking_users:
                    return account, global_ranking_users[key]

            if is_chine(account):
                if stop or not n_chinese_accounts_parse:
                    return account, False
                n_chinese_accounts_parse -= 1
            else:
                if stop:
                    return account, False

            page = False
            try:
                if is_chine(account):
                    ret = {'contests': get_all_contests()}

                    page = Statistic._get(
                        'https://leetcode-cn.com/graphql',
                        post=b'''
                        {"operationName":"userPublicProfile","variables":{"userSlug":"''' + account.key.encode() + b'''"},"query":"query userPublicProfile($userSlug: String!) { userProfilePublicProfile(userSlug: $userSlug) { username profile { userSlug realName contestCount ranking { currentLocalRanking currentGlobalRanking currentRating ratingProgress totalLocalUsers totalGlobalUsers } } }}"}''',  # noqa
                        content_type='application/json',
                    )
                    ret['profile'] = json.loads(page)['data']
                    page = ret
                else:
                    with rate_limiter:
                        url = resource.profile_url.format(**account.dict_with_info())
                        page = Statistic._get(url)
            except FailOnGetResponse as e:
                if is_chine(account):
                    nonlocal code_errors
                    code_errors[e.code] += 1
                    if code_errors[e.code] > 20:
                        n_chinese_accounts_parse = 0
                code = e.code
                if code == 404:
                    page = None
                else:
                    page = False
                    if code == 429:
                        stop = True

            return account, page

        def fetch_global_ranking_users(page_index):
            nonlocal n_chinese_accounts_parse
            if not n_chinese_accounts_parse:
                return page_index, None

            for attempt in range(3):
                try:
                    page = Statistic._get(
                        'https://leetcode-cn.com/graphql',
                        post=b'''
                        {"operationName":"null","variables":{},"query":"{globalRanking(page: ''' + str(page_index).encode() + b''') { rankingNodes { dataRegion user { username profile { userSlug realName contestCount ranking { currentLocalRanking currentGlobalRanking currentRating ratingProgress totalLocalUsers totalGlobalUsers } } } }  } }"}''',  # noqa
                        content_type='application/json',
                    )
                    ret = json.loads(page)['data']
                    return page_index, ret

                except FailOnGetResponse as e:
                    nonlocal code_errors
                    code_errors[e.code] += 1
                    if code_errors[e.code] > 20:
                        n_chinese_accounts_parse = 0
                    if e.code == 504:
                        time.sleep(attempt)
                        continue
                    break
            return page_index, None

        if os.path.exists(Statistic.STATE_FILE):
            with open(Statistic.STATE_FILE, 'r') as fo:
                state = yaml.safe_load(fo)
        else:
            state = {}

        last_page = state.setdefault('last_page', 0)
        n_accounts_to_paging = state.setdefault('n_accounts_to_paging', 10)
        pages_per_update = state.setdefault('pages_per_update', 500)
        n_chinese_accounts_parse = state.setdefault('n_chinese_accounts_parse', 1000)
        if len(accounts) > n_accounts_to_paging:
            if (
                'next_time' in state
                and datetime.now() < state['next_time']
                and last_page == 0
            ):
                for a in accounts:
                    if not is_chine(a):
                        a.updated = state['next_time']
                        a.save()
                next_page = last_page
            else:
                next_page = last_page + pages_per_update
            state['last_page'] = next_page
            pages = set(list(range(last_page + 1, next_page + 1)))
            stop = True
        else:
            pages = set()
            stop = False

        for a in tqdm.tqdm(accounts, desc='getting global ranking pages'):
            if 'global_ranking_page' in a.info:
                page = a.info.pop('global_ranking_page')
                pages.add(page)
                a.save()

        global_ranking_users = {}
        with PoolExecutor(max_workers=8) as executor, tqdm.tqdm(desc='global ranking paging', total=len(pages)) as pb:
            for page, data in executor.map(fetch_global_ranking_users, pages):
                pb.set_postfix(page=page)
                pb.update()
                if data is None:
                    continue
                if data:
                    data = data['globalRanking']['rankingNodes']
                if data:
                    for node in data:
                        data_region = node['dataRegion']
                        data_region = '' if data_region == 'US' else f'-{data_region.lower()}'
                        username = node['user']['profile']['userSlug']
                        global_ranking_users[(data_region, username)] = {
                            'profile': {'userProfilePublicProfile': node['user']},
                            'contests': get_all_contests(),
                        }
                else:
                    state['last_page'] = 0
                    state['next_time'] = datetime.now() + timedelta(hours=8)
                    break

        with open(Statistic.STATE_FILE, 'w') as fo:
            yaml.dump(state, fo, indent=2)

        with PoolExecutor(max_workers=2) as executor:
            for account, page in executor.map(fetch_profile_data, accounts):
                if pbar:
                    pbar.set_postfix(stop=stop, n_chinese=n_chinese_accounts_parse)
                    pbar.update()

                if not page:
                    if page is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue

                info = {}
                contest_addition_update_by = None
                ratings, titles = [], []
                if is_chine(account) or isinstance(page, dict):
                    contests = [c['titleSlug'] for c in page['contests']['allContests']]
                    info = page['profile']['userProfilePublicProfile']
                    if info is None:
                        yield {'info': None}
                        continue
                    info.update(info.pop('profile', {}) or {})
                    info.update(info.pop('ranking', {}) or {})
                    info['slug'] = info.pop('userSlug')
                    ratings = info.pop('ratingProgress', []) or []
                    contests = contests[len(contests) - len(ratings):]
                    titles = list(reversed(contests))
                    if 'currentRating' in info:
                        info['rating'] = int(info['currentRating'])
                else:
                    for regex, to_number in (
                        (r'<li[^>]*>\s*<span[^>]*>(?P<value>[^<]*)</span>\s*<i[^>]*>[^<]*</i>(?P<key>[^<]*)', True),
                        (r'<[^>]*class="(?P<key>realname|username)"[^>]*title="(?P<value>[^"]*)"[^>]*>', False),
                        (r'<[^>]*data-user-(?P<key>slug)="(?P<value>[^"]*)"[^>]*>', False),
                    ):
                        matches = re.finditer(regex, page)

                        for match in matches:
                            key = html.unescape(match.group('key')).strip().replace(' ', '_').lower()
                            value = html.unescape(match.group('value')).strip()
                            if to_number and value.isdigit():
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

                for k in ('profile_url', ):
                    if k in account.info:
                        info[k] = account.info[k]

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
                            last_rating = int_rating
                        prev_rating = rating
                if last_rating and 'rating' not in info:
                    info['rating'] = last_rating

                if 'rating' in info:
                    info['rating_ts'] = int(datetime.now().timestamp())

                if 'global_ranking' in info:
                    global_ranking = int(re.split('[^0-9]', info['global_ranking'])[0])
                elif 'currentGlobalRanking' in info:
                    global_ranking = info['currentGlobalRanking']
                else:
                    global_ranking = None
                if global_ranking:
                    page = (int(global_ranking) + 24) // 25
                    info['global_ranking_page'] = page

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': contest_addition_update_by,
                        'clear_rating_change': True,
                    },
                    'replace_info': True,
                }

                assert info and info['slug'] == account.key, \
                    f'Account key {account.key} should be equal username {info["slug"]}'

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
