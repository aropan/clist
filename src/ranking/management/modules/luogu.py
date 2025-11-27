#!/usr/bin/env python3

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from clist.templatetags.extras import camel_to_snake, get_item
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import FailOnGetResponse


class Statistic(BaseModule):

    PROBLEM_URL_FORMAT_ = '/problem/{code}?contestId={cid}'
    API_CONTEST_URL_FORMAT_ = '/contest/{cid}?_contentOnly'
    SCOREBOARD_URL_FORMAT_ = '{url}#scoreboard'
    API_SCOREBOARD_URL_FORMAT_ = '/fe/api/contest/scoreboard/{cid}?page={page}'
    API_USER_URL_FORMAT_ = '/user/{user}?_contentOnly'
    API_RATING_ELO_URL_FORMAT_ = '/api/rating/elo?user={user}&page={page}'

    @staticmethod
    def _get(*args, **kwargs):
        additional_attempts = {
            403: {
                'count': 8,
                'func': lambda e: e.has_message(r'\u8bf7\u6c42\u9891\u7e41\uff0c\u8bf7\u7a0d\u5019\u518d\u8bd5'),  # frequent requests, please try again later  # noqa
            },
            429: {'count': 5},
        }
        return REQ.get(*args, **kwargs, additional_attempts=additional_attempts, additional_delay=50, n_attempts=3)

    def get_standings(self, users=None, statistics=None, **kwargs):
        is_icpc = self.contest.standings_kind == 'icpc'
        with_partial = self.contest.standings_kind not in {'cf'}
        standings_url = Statistic.SCOREBOARD_URL_FORMAT_.format(url=self.url)
        api_contest_url = urljoin(self.url, Statistic.API_CONTEST_URL_FORMAT_).format(cid=self.key)
        api_scoreboard_url_format = urljoin(self.url, Statistic.API_SCOREBOARD_URL_FORMAT_)

        contest_data = Statistic._get(api_contest_url, return_json=True)
        if contest_data.get('code') == 404:
            return {'action': 'delete'}

        contest_problems = get_item(contest_data, 'currentData.contestProblems')
        problems_infos = OrderedDict()
        if contest_problems:
            for idx, problem in enumerate(contest_problems):
                problem.update(problem.pop('problem', {}))

                code = str(problem.pop('pid'))
                problem_info = {
                    'short': chr(ord('A') + idx),
                    'code': code,
                    'name': problem.pop('title'),
                    'url': urljoin(self.url, Statistic.PROBLEM_URL_FORMAT_).format(cid=self.key, code=code),
                }
                if problem.get('score'):
                    problem_info['full_score'] = problem.pop('score')
                for k, v in problem.items():
                    k = camel_to_snake(k)
                    if k not in problem_info:
                        problem_info[k] = v
                if is_icpc:
                    problem_info.pop('full_score', None)
                problems_infos[code] = problem_info

        @RateLimiter(max_calls=1, period=1)
        def fetch_page(page):
            url = api_scoreboard_url_format.format(cid=self.key, page=page)
            data = Statistic._get(url, return_json=True)
            data['_standings_page'] = page
            return data

        result = {}
        n_pages = None
        last_score = None
        last_rank = None
        rank = 0
        time_divider = 1 if is_icpc else 1000

        def process_page(data):
            nonlocal n_pages
            scoreboard = data.pop('scoreboard')
            scoreboard_result = scoreboard.pop('result')
            n_pages = (scoreboard['count'] - 1) // scoreboard['perPage'] + 1

            for entry in scoreboard_result:
                user = entry.pop('user')
                member = str(user.pop('uid'))
                row = result.setdefault(member, {'member': member})

                if '_standings_pages' in row:
                    row['_standings_pages'].append(data['_standings_page'])
                elif '_standings_page' in row:
                    row['_standings_pages'] = [row.pop('_standings_page'), data['_standings_page']]
                else:
                    row['_standings_page'] = data['_standings_page']

                row['name'] = user.pop('name')
                if 'runningTime' in entry:
                    time_in_seconds = entry.pop('runningTime') / time_divider
                    penalty = round(time_in_seconds / 60) if is_icpc else self.to_time(time_in_seconds, 3)
                    row['penalty'] = penalty
                avatar = user.pop('avatar')
                if avatar:
                    row['info'] = {'avatar': avatar}
                row['solving'] = entry.pop('score')

                problems = row.setdefault('problems', {})
                for code, problem_result in (entry.pop('details') or {}).items():
                    code = str(code)
                    problem_info = problems_infos.setdefault(code, {'code': code, 'short': code})
                    short = problem_info['short']
                    p = problems.setdefault(short, {})
                    score = problem_result.pop('score', None)
                    if problem_result.get('runningTime'):
                        time_in_seconds = problem_result.pop('runningTime') / time_divider
                        p['time'] = self.to_time(time_in_seconds / 60, 2)
                        if is_icpc:
                            p['time_in_seconds'] = time_in_seconds
                    if score is not None:
                        if is_icpc:
                            if score == 0:
                                p['result'] = '+'
                            elif score > 0:
                                p['result'] = f'+{score}'
                            else:
                                p['result'] = str(score)
                        else:
                            p['result'] = score
                        if with_partial and 'full_score' in problem_info and p['result'] < problem_info['full_score']:
                            p['partial'] = True

                if statistics and member in statistics:
                    stats = statistics[member]
                    for f in 'old_rating', 'rating_change', 'new_rating':
                        if f in stats and f not in row:
                            row[f] = stats[f]

                nonlocal rank, last_score, last_rank
                rank += 1
                curr_score = (row['solving'], row.get('penalty'))
                if curr_score != last_score:
                    last_score = curr_score
                    last_rank = rank
                row['place'] = last_rank
        for row in result.values():
            row.pop('_standings_page', None)

        data = fetch_page(1)

        process_page(data)
        with PoolExecutor(max_workers=2) as executor:
            for data in executor.map(fetch_page, range(2, n_pages + 1)):
                process_page(data)

        standings = {
            'url': standings_url,
            'result': result,
            'problems': list(problems_infos.values()),
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        api_user_url = urljoin(resource.url, Statistic.API_USER_URL_FORMAT_)
        api_rating_elo_url = urljoin(resource.url, Statistic.API_RATING_ELO_URL_FORMAT_)

        @RateLimiter(max_calls=2, period=1)
        def fetch_profile(user):
            ret = {'username': user}

            ratings = []
            n_pages = None
            page = 0
            while n_pages is None or page <= n_pages:
                page += 1
                url = api_rating_elo_url.format(user=user, page=page)
                try:
                    data = Statistic._get(url, return_json=True)
                except FailOnGetResponse:
                    return False
                records = data['records']
                n_pages = records['count'] / records['perPage']
                ratings.extend(records['result'])
            ret['ratings'] = ratings

            url = api_user_url.format(user=user)
            try:
                data = Statistic._get(url, return_json=True)
            except FailOnGetResponse:
                return False
            if data.get("__no_json"):
                match = re.search('<script[^>]*id="lentille-context"[^>]*>(?P<data>[^<]*)</script>', data["page"])
                data = json.loads(match.group("data"))
                user_data = get_item(data, 'data.user') or {}
            else:
                user_data = get_item(data, 'currentData.user') or {}
            for k, v in user_data.items():
                if isinstance(v, (dict, list)):
                    continue
                if len(str(v)) > 200:
                    continue
                k = camel_to_snake(k)
                if k not in ret:
                    ret[k] = v

            return ret

        with PoolExecutor(max_workers=4) as executor:
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

                assert user == data.pop('username')

                ret = {'info': data}

                contest_addition_update = {}
                for rating in data.pop('ratings'):
                    contest_id = str(rating['contest']['id'])
                    update = contest_addition_update.setdefault(contest_id, OrderedDict())
                    if rating.get('rating') is None:
                        continue
                    update['new_rating'] = rating['rating']
                    if rating.get('prevDiff') is not None:
                        update['rating_change'] = rating['prevDiff']
                        update['old_rating'] = rating['rating'] - rating['prevDiff']
                    if rating.get('latest') and rating.get('rating'):
                        data['rating'] = rating['rating']

                if contest_addition_update:
                    ret['contest_addition_update_params'] = {
                        'update': contest_addition_update,
                        'clear_rating_change': True,
                    }

                yield ret
