#!/usr/bin/env python3

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule
from utils.timetools import parse_datetime


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        url = urljoin(self.resource.parse_url, f'/api/contests/{self.key}')
        data = REQ.get(url, return_json=True)
        data = data.get('data') or {}
        problems_data = data.get('problems') or []
        problems_infos = OrderedDict()
        for idx, problem_data in enumerate(problems_data):
            problem_data = problem_data['questionId']
            short = chr(ord('A') + idx)
            problem_info = {
                'code': problem_data['_id'],
                'name': problem_data['questionTitle'],
                'short': short,
            }
            if problem_data.get('questionCategory'):
                problem_info['tags'] = [problem_data['questionCategory'].lower()]
            problem_info['url'] = urljoin(self.host, f'/contest/{self.info["parse"]["slug"]}/{problem_info["name"]}?questionId={problem_info["code"]}&contestId={self.key}')  # noqa
            problem_info['archive_url'] = urljoin(self.host, f'/questions/{problem_info["name"]}?questionId={problem_info["code"]}')  # noqa
            problems_infos[problem_info['code']] = problem_info

        url = urljoin(self.resource.parse_url, f'/api/contests/ranking/{self.key}')
        data = REQ.get(url, return_json=True)

        result = {}
        users = []
        for row in data['rankings']:
            handle = row['user']
            r = result.setdefault(handle, {'member': handle})
            r['place'] = row.pop('rank')
            r['solving'] = row.pop('totalScore')
            finish_time = row.pop('finishTime')
            if finish_time:
                penalty = (parse_datetime(finish_time) - self.start_time).total_seconds()
                r['penalty'] = self.to_time(penalty, num=3)

            stat = (statistics or {}).get(handle, {})
            if 'name' in stat:
                r['name'] = stat['name']
            else:
                users.append(handle)

        for user_info in Statistic.get_users_infos(users, self.resource, None):
            user_info = user_info['info']
            r = result[user_info['_id']]
            r['info'] = user_info
            if user_info.get('name'):
                r['name'] = user_info['name']

        standings = {
            'result': result,
            'problems': list(problems_infos.values()),
        }

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=10, period=1)
        def fetch_profile(user):
            url = urljoin(resource.parse_url, f'/api/users/{user}')
            data = REQ.get(url, return_json=True)
            data = data.get('data') or {}

            name = ' '.join(data[field] for field in ['firstName', 'lastName'] if data.get(field))
            data['name'] = name

            if 'stats' in data and 'submissionHeatmap' in data['stats']:
                data['stats'].pop('submissionHeatmap')

            if data.get('image'):
                data['avatar_url'] = data.pop('image')
            else:
                data.pop('avatar_url')

            return data

        with PoolExecutor(max_workers=10) as executor:
            profiles = executor.map(fetch_profile, users)
            for user, data in zip(users, profiles):
                if pbar:
                    pbar.update()

                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                assert user == data['_id']

                ret = {'info': data}
                yield ret
