#!/usr/bin/env python3

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from clist.templatetags.extras import get_item, normalize_field
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    API_PROBLEMS_URL_FORMAT_ = 'https://api.algoleague.com/api/app/contests-problem/get-problems-info?ContestId={contest_id}'  # noqa: E501
    API_STANDINGS_URL_FORMAT_ = 'https://api.algoleague.com/api/app/contests-score?ContestId={contest_id}&SkipCount={offset}&MaxResultCount={count}'  # noqa: E501
    API_USER_PREVIEW_FORMAT_ = 'https://api.algoleague.com/api/app/app-user-preview/{}'

    def get_standings(self, users=None, statistics=None, **kwargs):
        strip_url = self.url.rstrip('/')
        standings_url = f'{strip_url}/leaderboard'
        contest_id = get_item(self, 'info.parse.id')

        problems_url = self.API_PROBLEMS_URL_FORMAT_.format(contest_id=contest_id)
        problems_data = REQ.get(problems_url, return_json=True)
        problems_infos = OrderedDict()
        for problem_num, problem_data in enumerate(problems_data['items']):
            code = problem_data['id']
            slug = problem_data['slug']
            problem = {
                'code': code,
                'short': chr(ord('A') + problem_num),
                'name': problem_data['name'],
                'slug': slug,
                'url': f'{strip_url}/problem/{slug}',
            }
            problems_infos[code] = problem

        page = 0
        count = 100
        total_pages = 1
        result = {}
        participant_type = get_item(self, 'info.parse.participationType').lower()
        if participant_type == 'team':
            profile_type = 'team'
        elif participant_type == 'individual':
            profile_type = 'profile'
        else:
            raise ExceptionParseStandings('Unknown participant type: ' + participant_type)

        while page < total_pages:
            url = self.API_STANDINGS_URL_FORMAT_.format(contest_id=contest_id, offset=page * count, count=count)
            data = REQ.get(url, return_json=True)
            for row_data in data['items']:
                info = {'profile_url': {'type': profile_type}}
                handle = row_data.pop('creatorId')
                name = row_data.pop('name')
                if profile_type == 'profile':
                    handle = name
                if not handle:
                    info['_no_profile_url'] = True
                    info['name'] = name
                    handle = f'{profile_type}:{name}'
                row = result.setdefault(handle, {'member': handle})
                row['solving'] = row_data.pop('totalSolved')
                penalty = row_data.pop('totalPenalty')
                row['penalty'] = (penalty - 1) // 60 + 1
                row['time'] = penalty
                if profile_type == 'team':
                    row['name'] = name
                    info['is_team'] = True
                row['info'] = info

                problems = row.setdefault('problems', {})
                for problem_score in row_data.pop('scores'):
                    problem_code = problem_score['problemId']
                    if problem_code not in problems_infos:
                        continue
                    short = problems_infos[problem_code]['short']
                    problem = problems.setdefault(short, {})
                    status = (problem_score['status'] or '').lower()
                    attempts = problem_score['retryCount']
                    if status == 'solved':
                        attempts -= 1
                        problem['result'] = '+' + (str(attempts) if attempts else '')
                    elif status == 'unsolved' or not status:
                        problem['result'] = f'-{attempts}'
                    else:
                        problem['result'] = f'?{attempts}'
                    time = problem_score['time']
                    if time:
                        problem['time_in_seconds'] = time
                        problem['time'] = self.to_time(time, num=3)
                if not problems:
                    result.pop(handle)
                    continue
            total_pages = (data['totalCount'] - 1) // count + 1
            page += 1

        sorted_rows = sorted(result.values(), key=lambda x: (-x['solving'], x['time']))
        last_score, last_rank = None, None
        for rank, row in enumerate(sorted_rows, start=1):
            score = (row['solving'], row['time'])
            if score != last_score:
                last_score, last_rank = score, rank
            row['place'] = last_rank

        standings = {
            'url': standings_url,
            'problems': list(problems_infos.values()),
            'result': result,
            'hidden_fields': ['time'],
            'writers': [],
        }

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_profile(user, account):
            if account.info.get('is_team') or account.info.get('_no_profile_url'):
                return False

            try:
                url = Statistic.API_USER_PREVIEW_FORMAT_.format(user)
                data = REQ.get(url, return_json=True)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                return False

            info = {}
            data = data['profile']
            avatar_url = data.pop('image', None)
            if avatar_url:
                info['avatar_url'] = avatar_url
            info_data = info.setdefault('data_', {})
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    continue
                key = normalize_field(key)
                info_data[key] = value
            return info

        with PoolExecutor(max_workers=1) as executor:
            for info in executor.map(fetch_profile, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue
                info = {'info': info}
                yield info
