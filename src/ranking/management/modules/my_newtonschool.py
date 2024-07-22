#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import json
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse


class Statistic(BaseModule):
    API_STANDING_URL_FORMAT_ = '/api/v1/course/h/{}/assignment/h/{}/leader_board/competition/'
    API_PROBLEMS_URL_FORMAT_ = '/api/v1/course/h/{}/assignment/h/{}/details/public/'
    API_PROBLEM_URL_FORMAT_ = '/api/v1/course/h/{}/assignment/h/{}/question/h/{}/details/'
    API_PROFILE_URL_FORMAT_ = '/api/v1/user/{}/'

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = urljoin(self.url, '?tab=leaderboard')

        hashes = self.key.split('/')
        url = urljoin(self.url, self.API_PROBLEMS_URL_FORMAT_.format(*hashes))
        page = REQ.get(url)
        data = json.loads(page)
        problems_infos = collections.OrderedDict()
        for idx, question in enumerate(data['assignment_questions'], start=1):
            short = f'Q{idx}'
            code = question['hash']
            problems_infos[code] = dict(
                code=code,
                name=question['question_title'],
                short=short,
            )

        url = urljoin(self.url, self.API_STANDING_URL_FORMAT_.format(*hashes))

        limit = 100
        results = {}

        @RateLimiter(max_calls=4, period=1)
        def process_page(n_page):
            page = REQ.get(f'{url}?limit={limit}&offset={n_page * limit}')
            data = json.loads(page)

            for r in data['results']:
                row = collections.OrderedDict()
                row['place'] = r.pop('actual_rank')
                if 'user' in r:
                    user = r.pop('user')
                elif 'course_user_mapping' in r:
                    user = r.pop('course_user_mapping').pop('user')
                member = user.pop('username')
                row['member'] = member
                row['name'] = user.pop('first_name') + ' ' + user.pop('last_name')
                row['penalty'] = r.pop('penalty')
                row['solving'] = r.pop('all_test_cases_passed_question_count')
                last_solved = r.pop('latest_solved_question_timestamp')
                if last_solved is not None:
                    row['last_solved'] = last_solved / 1000
                country = r.pop('country', {}).get('code')
                if country:
                    row['country'] = country
                college = r.pop('college', {}).get('name')
                if college:
                    row['college'] = college

                info = user.pop('profile', {})
                rating = user.get('contest_rating')
                if rating is not None:
                    info['rating'] = rating
                if info:
                    row['info'] = info

                problems = row.setdefault('problems', {})
                for p in r.pop('assignment_course_user_question_mappings'):
                    attempt = p.pop('wrong_submissions')
                    accepted = p.pop('all_test_case_passed')
                    if not accepted and not attempt:
                        continue
                    short = problems_infos[p.pop('assignment_question')['hash']]['short']
                    problem = problems.setdefault(short, {})
                    if accepted:
                        problem['result'] = '+' if attempt == 0 else f'+{attempt}'
                    elif attempt:
                        problem['result'] = f'-{attempt}'
                    time = p.pop('time_in_minutes')
                    if time is not None:
                        problem['time'] = self.to_time(time, 2)
                if not problems:
                    continue

                if statistics and member in statistics:
                    stat = statistics[member]
                    for k in ('rating_change', 'new_rating', '_rank'):
                        if k in stat:
                            row[k] = stat[k]

                results[member] = row

            return data

        with PoolExecutor(max_workers=4) as executor:
            data = process_page(0)
            n_total_page = (data['count'] - 1) // limit + 1
            executor.map(process_page, range(1, n_total_page))

        ret = {
            'url': standings_url,
            'fields_types': {'last_solved': ['time']},
            'hidden_fields': ['last_solved', 'college'],
            'problems': list(problems_infos.values()),
            'result': results,
        }
        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_user(user):
            url = urljoin(resource.url, Statistic.API_PROFILE_URL_FORMAT_.format(user))
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return user, None, {}
                return user, False, {}

            data = json.loads(page)
            contest_ratings = data.pop('contest_ratings', [])
            data.update(data.pop('profile', {}))

            info = {}
            avatar = data.pop('avatar', None)
            if avatar:
                info['avatar'] = avatar
            info['data_'] = data

            ratings = {}
            for stat in contest_ratings:
                course = stat['course']
                key = f'{course["hash"]}/{course["assignment_hash"]}'
                rating = ratings.setdefault(key, collections.OrderedDict())
                rating['rating_change'] = stat['rating_delta']
                rating['new_rating'] = stat['rating']
                rating['_rank'] = stat['rank']

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
                        'clear_rating_change': True,
                    },
                }
                yield info
