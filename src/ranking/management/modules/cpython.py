# -*- coding: utf-8 -*-

import copy
import json
import os
import re
from collections import OrderedDict
from time import sleep
from urllib.parse import urljoin

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import FailOnGetResponse
from utils.timetools import parse_datetime


def query(url, *args, **kwargs):
    url = urljoin(url, '?format=json')
    n_attempt = 5
    for attempt in range(n_attempt):
        try:
            return REQ.get(url, *args, **kwargs, return_json=True)
        except FailOnGetResponse as e:
            if attempt + 1 == n_attempt or e.code != 429:
                raise e

            sleep_time = 2 ** attempt
            try:
                data = json.loads(e.response)
                match = re.search('available in (?P<seconds>[0-9]+) second', data['detail'])
                sleep_time = int(match.group('seconds')) + 1
            except Exception:
                pass
            sleep(sleep_time)


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        parse_info = self.info.get('parse', {})
        authors = parse_info.get('authors', [])
        is_rated = parse_info.get('isRated', False)

        api_problems_url = urljoin(self.url, f'/api/contests/{self.key}/problems')
        try:
            data = query(api_problems_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e

        problems_infos = OrderedDict()
        problems_full_scores = {}
        for problem in data:
            short = problem['symbol']
            code = problem['problem']['id']
            problem_info = {
                'short': short,
                'name': problem['problem']['title'],
                'code': code,
                'url': urljoin(self.url, f'/practice/problems/problem/{code}'),
            }
            problems_full_scores[short] = problem['ball']
            if problem['ball'] > 1:
                problem_info['full_score'] = problem['ball']
            problems_infos[short] = problem_info

        api_standings_url = urljoin(self.url, f'/api/contests/{self.key}/contestants')
        data = query(api_standings_url)

        hidden_fields = {'performance'}
        result = OrderedDict()
        grouped_team = False
        has_penalty = False
        for row in data:
            r = OrderedDict()
            team = row.pop('team')

            if team:
                rows = []
                row['name'] = team['name']
                row['_no_update_name'] = True
                row['_members'] = [{'account': m['username']} for m in team['members']]
                for member in team['members']:
                    new_row = copy.deepcopy(row)
                    new_row.update(member)
                    rows.append(new_row)
                grouped_team = True
                hidden_fields |= {'old_rating', 'new_rating'}
            else:
                rows = [row]

            for row in rows:
                handle = row.pop('username')
                if re.match('cholpan[0-9]*', handle):
                    continue
                r = result.setdefault(handle, {'member': handle})
                is_unrated = row.get('isUnrated')
                if not is_unrated and is_rated:
                    r['old_rating'] = row.pop('rating')
                    r['rating_change'] = row.pop('delta')
                    r['new_rating'] = row.pop('newRating')
                else:
                    row.pop('rating', None)
                    row.pop('delta', None)
                    row.pop('newRating', None)

                if team:
                    r['name'] = row.pop('name')
                    r['_members'] = row.pop('_members')
                    r['_no_update_name'] = row.pop('_no_update_name')

                performance = row.pop('perfomance', row.pop('performance', None))
                if performance is not None:
                    r['performance'] = performance
                r['place'] = row.pop('rank')
                r['solving'] = row.pop('points')
                r['penalty'] = row.pop('penalties')
                upsolving = row.get('isVirtual')
                problems = r.setdefault('problems', {})
                for problem_info in row.pop('problemsInfo'):
                    short = problem_info['problemSymbol']
                    problem = problems.setdefault(short, {})
                    if upsolving:
                        problem = problem.setdefault('upsolving', {})
                    attempts = problem_info['attemptsCount']
                    if problem_info['points'] and problems_full_scores[short] == 1:
                        problem['result'] = '+' if attempts == 0 else f'+{attempts}'
                    elif not problem_info['points'] and attempts:
                        problem['result'] = f'-{attempts}'
                    else:
                        problem['result'] = problem_info['points']
                    if problem_info['points'] > 0 and problem_info['theBest']:
                        problem['max_score'] = True

                    if problem_info['penalties']:
                        has_penalty = True

                    accepted_time = problem_info.get('firstAcceptedTime')
                    if accepted_time:
                        accepted_time = parse_datetime(accepted_time)
                        problem['time'] = self.to_time((accepted_time - self.start_time).total_seconds() // 60, 2)
                        problem['time_in_seconds'] = (accepted_time - self.start_time).total_seconds()

                for k, v in row.items():
                    if k not in r:
                        r[k] = v
                        hidden_fields.add(k)

                if not problems and not r['solving']:
                    result.pop(handle)

        if not has_penalty:
            for row in result.values():
                row.pop('penalty')

        standings = {
            'url': os.path.join(self.url, 'standings'),
            'result': result,
            'problems': list(problems_infos.values()),
            'hidden_fields': list(hidden_fields),
            'grouped_team': grouped_team,
            'writers': [author['username'] for author in authors],
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_profile(handle=False):
            info = {}

            api_contest_rating_url = urljoin(resource.url, f'/api/contests-rating/{handle}')
            api_user_info_url = urljoin(resource.url, f'/api/users/{handle}/info')
            api_problems_rating_url = urljoin(resource.url, f'/api/problems-rating/{handle}')
            api_challenges_rating_url = urljoin(resource.url, f'/api/challenges-rating/{handle}')
            api_social_url = urljoin(resource.url, f'/api/users/{handle}/social')

            for url, dst in (
                (api_contest_rating_url, info),
                (api_user_info_url, info),
                (api_social_url, info),
                (api_problems_rating_url, info.setdefault('problems', {})),
                (api_challenges_rating_url, info.setdefault('challenges', {})),
            ):
                try:
                    data = query(url)
                except FailOnGetResponse as e:
                    if e.code == 404:
                        return None
                    return False
                dst.update(data)

            return info

        for user in users:
            data = fetch_profile(user)
            if pbar:
                pbar.update()
            if not data:
                if data is None:
                    yield {'delete': True}
                else:
                    yield {'skip': True}
                continue

            assert user.lower() == data['username'].lower()

            ret = {'info': data}

            yield ret
