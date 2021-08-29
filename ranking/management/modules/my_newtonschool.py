#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import json
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):
    API_STANDING_URL_FORMAT_ = '/api/v1/course/h/{}/assignment/h/{}/leader_board/competition/'
    API_PROBLEM_URL_FORMAT_ = '/api/v1/course/h/{}/assignment/h/{}/details/public/'

    def get_standings(self, users=None, statistics=None):
        standings_url = urljoin(self.url, '?tab=leaderboard')

        hashes = self.key.split('/')
        url = urljoin(self.url, self.API_PROBLEM_URL_FORMAT_.format(*hashes))
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
                user = r.pop('course_user_mapping').pop('user')
                row['member'] = user.pop('username')
                row['name'] = user.pop('first_name') + ' ' + user.pop('last_name')
                row['penalty'] = r.pop('penalty')
                row['solving'] = r.pop('all_test_cases_passed_question_count')
                last_solved = r.pop('latest_solved_question_timestamp')
                if last_solved is not None:
                    row['last_solved'] = last_solved / 1000
                row['info'] = user.pop('profile')

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
                results[row['member']] = row

            return data

        with PoolExecutor(max_workers=4) as executor:
            data = process_page(0)
            n_total_page = (data['count'] - 1) // limit + 1
            executor.map(process_page, range(1, n_total_page))

        ret = {
            'url': standings_url,
            'fields_types': {'last_solved': ['time']},
            'hidden_fields': ['last_solved'],
            'problems': list(problems_infos.values()),
            'result': results,
        }
        return ret
