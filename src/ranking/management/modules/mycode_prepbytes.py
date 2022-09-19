#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from pprint import pprint  # noqa

import coloredlogs
import dateutil.parser
import pytz
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        api_server_url = self.info['parse'].get('contestServerUrl')
        now = datetime.utcnow().replace(tzinfo=pytz.utc)
        if not api_server_url or self.end_time + timedelta(days=1) < now:
            api_server_url = 'https://server.prepbytes.com'
        api_server_url = api_server_url.rstrip('/')

        url = f'{api_server_url}/api/contest/getTotalParticipants'
        page = REQ.get(url, post={'contestId': self.key})
        data = json.loads(page)
        if data.get('code') != 200 or data.get('data') is None:
            raise ExceptionParseStandings(f'resposnse = {data}')
        total = data['data']

        per_page = 1000

        def fetch_leaderboard_page(page):
            url = f'{api_server_url}/api/contest/getLeaderboardByPage'
            data = {
                'contestId': self.key,
                'page': page + 1,
                'usersPerPage': per_page,
            }
            page = REQ.get(url, post=data)
            data = json.loads(page)
            return data

        results = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_leaderboard_page, range((total + per_page - 1) // per_page)):
                if data.get('code') != 200 or data.get('data') is None:
                    raise ExceptionParseStandings(f'resposnse = {data}')
                for r in data['data']:
                    handle = r.pop('user_id', r.pop('member', None))
                    if not handle:
                        logger.warning(f'skip row = {r}')
                        continue
                    row = results.setdefault(handle, {'member': handle})
                    row['place'] = r.pop('rank')
                    row['solving'] = r.pop('score')
                    row['name'] = r.pop('name')

                    stat = (statistics or {}).get(handle, {})
                    if stat:
                        for field in 'old_rating', 'rating_change', 'new_rating', 'solved', 'problems':
                            if field in stat and field not in row:
                                row[field] = stat[field]

        url = f'{api_server_url}/api/contest/problems'
        page = REQ.get(url, post={'contestId': self.key})
        data = json.loads(page)
        problems = []
        for p in data['data']:
            problem = {
                'code': p['problem_id'],
                'short': p['problem_id'],
                'name': p['problem_name'],
            }
            if p.get('tags'):
                tags = json.loads(p['tags'])
                if tags:
                    problem['tags'] = tags['topicwise']
            if p.get('topicWiseData'):
                topic_wise_data = json.loads(p['topicWiseData'])
                problem['url'] = f'https://mycode.prepbytes.com/submit/{p["problem_id"]}'
                if isinstance(topic_wise_data, dict):
                    contest_wise = topic_wise_data.get('contestwise')
                    if contest_wise:
                        contest = contest_wise[0]
                        problem['url'] = f'https://mycode.prepbytes.com/contest/{contest}/problems/{p["problem_id"]}'
                elif topic_wise_data:
                    topic = topic_wise_data[0]['topic']
                    problem['url'] = f'https://mycode.prepbytes.com/problems/{topic}/{p["problem_id"]}'
            problems.append(problem)

        ret = {
            'url': os.path.join(self.url, 'leaderboard'),
            'result': results,
            'problems': problems,
        }
        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=8, period=2)
        def fetch_user_info(user):
            page = REQ.get('https://server.prepbytes.com/api/profile/getProfileByUserId',
                           post=f'{{"userId":"{user}"}}',
                           content_type='application/json')
            data = json.loads(page)
            if isinstance(data, str) and 'You have exceeded' in data:
                logger.info(f'fetch user info data = {data}')
                return user, False, None
            if not isinstance(data, dict) or data.get('code') != 200 or data.get('data') is None:
                logger.warning(f'fetch user info data = {data}')
                return user, False, None
            data = data['data']

            contest_data = data.pop('contestData', [])
            rating_history = data.pop('ratingHistory', [])
            data.pop('solvedAndAttemptedProblemIds', None)
            data.pop('submissionActivity', None)

            ratings = {}
            prev_rating = None
            for h in rating_history:
                rating = ratings.setdefault(h['contestId'], {})
                int_rating = int(h['rating'])
                rating['new_rating'] = int_rating
                if prev_rating is not None:
                    rating['rating_change'] = int_rating - prev_rating
                    rating['old_rating'] = prev_rating
                prev_rating = int_rating

            contest_data = [c for c in contest_data if 'contest' in c]
            contest_data.sort(key=lambda c: dateutil.parser.parse(c['contest']['endAt']))

            def get_values(data):
                if data is None:
                    return []
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data['values']
                raise TypeError(f'Unknown data type = {type(data)}')

            for d in contest_data:
                if 'contest' not in d:
                    continue
                rating = ratings.setdefault(d['contest']['contestId'], {})
                problems = rating.setdefault('problems', {})
                for attempt in get_values(d['user'].get('attemptedProblemsIds')):
                    p = problems.setdefault(attempt, {})
                    p['binary'] = False
                    p['result'] = '-'
                n_solving = 0
                for attempt in get_values(d['user'].get('solvedProblemsIds')):
                    p = problems.setdefault(attempt, {})
                    p['binary'] = True
                    p['result'] = '+'
                    n_solving += 1
                p['solved'] = {'solving': n_solving}

            data.update(data.pop('userDetails', {}))
            data = {k: v for k, v in data.items() if not k.endswith('-history')}

            if prev_rating is not None:
                data['rating'] = prev_rating

            return user, data, ratings

        with PoolExecutor(max_workers=8) as executor:
            for user, info, ratings in executor.map(fetch_user_info, users):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue
                info = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': ratings,
                        'by': 'key',
                    },
                }
                yield info
