#!/usr/bin/env python3

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import timedelta

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    SCOREBOARD_URL_FORMAT_ = 'https://scoreboard.solved.ac/?contestId={cid}'
    API_SCOREBOARD_URL_FORMAT_ = 'https://solved.ac/api/v3/contest/scoreboard?contestId={cid}&page={page}&rated=true&rivals=false'  # noqa

    def get_standings(self, users=None, statistics=None):

        cid = self.info.get('parse', {}).get('arenaBojContestId')
        if cid is None:
            return ExceptionParseStandings

        def fetch_page(page):
            url = self.API_SCOREBOARD_URL_FORMAT_.format(cid=cid, page=page)
            return REQ.get(url, return_json=True)

        page_data = fetch_page(1)
        contest_data = page_data['contest']
        problems_infos = []
        for idx, problem in enumerate(contest_data['problems'], start=1):
            problem_url = f'https://www.acmicpc.net/contest/problem/{cid}/{idx}'
            problem_info = {
                'short': problem['displayNumber'],
                'name': problem['title'],
                'url': problem_url,
            }
            if problem.get('score'):
                problem_info['full_score'] = problem['score']
            problems_infos.append(problem_info)

        result = {}
        hidden_fields = set()

        def process_page(page_data):
            items = page_data['teams']['items']
            for item in items:
                handle = item.pop('handle')
                row = result.setdefault(handle, {'member': handle})
                row['solving'], row['penalty'] = item.pop('score')
                row['place'] = item.pop('rank')
                problems = row.setdefault('problems', {})
                for idx, problem in enumerate(item.pop('problems')):
                    if problem is None:
                        continue
                    attempt, _, verdict, score, penalty, *_ = problem
                    accepted = verdict.lower() == 'true'
                    problem_info = problems_infos[idx]
                    p = problems.setdefault(problem_info['short'], {})
                    if 'full_score' in problem_info:
                        p['partial'] = score < problem_info['full_score']
                        p['attempt'] = attempt
                        p['result'] = score
                    elif accepted:
                        p['result'] = '+' if attempt == 1 else f'+{attempt - 1}'
                    else:
                        p['result'] = f'-{attempt}'
                    if penalty:
                        p['time'] = penalty
                for k, v in item.items():
                    if k not in row:
                        hidden_fields.add(k)
                        row[k] = v
                if handle in statistics:
                    stat = statistics[handle]
                    for k in 'old_rating', 'rating_change', 'new_rating', 'performance':
                        if k in stat:
                            row[k] = stat[k]

        process_page(page_data)
        per_page = 50
        n_page = (page_data['teams']['count'] + per_page - 1) // per_page

        for page in range(2, n_page + 1):
            page_data = fetch_page(page)
            process_page(page_data)

        standings = {
            'result': result,
            'url': self.SCOREBOARD_URL_FORMAT_.format(cid=cid),
            'hidden_fields': list(hidden_fields),
            'problems': problems_infos,
        }

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=2)
        def fetch_profile(handle):
            profile_url = resource.profile_url.format(account=handle)
            profile_page = REQ.get(profile_url, n_attempts=3)
            search_result = re.search('<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<json>[^<]*)</script>', profile_page)
            profile_data = json.loads(search_result.group('json'))
            profile_data = profile_data['props']['pageProps']
            data = profile_data['user']
            if data is None:
                return True, None
            if 'arenaRating' in data:
                data['rating'] = data['arenaRating']
            data['avatar_url'] = (data.pop('profileImageUrl')
                                  or 'https://static.solved.ac/misc/360x360/default_profile.png')
            history = profile_data['contests']['items']
            return data, history

        with PoolExecutor(max_workers=8) as executor:
            profiles = executor.map(fetch_profile, users)
            for user, (data, history) in zip(users, profiles):
                if not isinstance(data, dict):
                    if data is True:
                        yield {'skip': True, 'delta': timedelta(days=1)}
                    else:
                        yield {'info': data}
                    continue

                history.sort(key=lambda h: h['arena']['endTime'])
                contest_addition_update = {}
                for idx, contest in enumerate(history):
                    contest_key = str(contest['arenaId'])
                    update = contest_addition_update.setdefault(contest_key, OrderedDict())
                    if idx:
                        update['old_rating'] = contest['ratingBefore']
                        update['rating_change'] = contest['change']
                    else:
                        update['old_rating'] = None
                        update['rating_change'] = None
                    update['new_rating'] = contest['ratingAfter']
                    update['performance'] = contest['performance']

                yield {
                    'info': data,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': 'key',
                        'clear_rating_change': True,
                    }
                }
