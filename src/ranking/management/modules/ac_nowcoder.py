#!/usr/bin/env python3

import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import tqdm
from django.utils import timezone
from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number, normalize_field
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings


class Statistic(BaseModule):
    API_STANDING_URL_FORMAT_ = '{0.host}acm-heavy/acm/contest/real-time-rank-data?id={0.key}'
    API_PROBLEM_URL_FORMAT_ = '{0.host}acm/contest/problem-list?&id={0.key}'
    API_RATING_HISTORY_URL_FORMAT_ = '{0}acm-heavy/acm/contest/rating-history?uid={1}'

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = f'{self.url}#rank'
        api_standings_url = self.API_STANDING_URL_FORMAT_.format(self)
        timestamp = int(timezone.now().timestamp() * 1000)

        problem_infos = []

        api_problem_url = self.API_PROBLEM_URL_FORMAT_.format(self)
        page = 1
        data = None
        while data is None or page < data['basicInfo']['pageCount']:
            url = f'{api_problem_url}&page={page}&_={timestamp}'
            data = REQ.get(url, return_json=True)
            data = data['data']
            for problem in data['data']:
                problem_info = dict(
                    short=problem['index'],
                    name=problem['title'],
                    code=problem['problemId'],
                    accepted_count=problem['acceptedCount'],
                    submit_count=problem['submitCount'],
                    url=f'{self.url}/{problem["index"]}',
                )

                if self.contest.standings_kind == 'scoring':
                    problem_info['full_score'] = problem['score']
                problem_infos.append(problem_info)
            page += 1

        result = OrderedDict()
        hidden_fields = set()

        def fetch_page(page):
            url = f'{api_standings_url}&page={page}&limit=0&_={timestamp}'
            data = REQ.get(url, return_json=True)
            return data['data']

        def process_page(data):
            rank_data = data['rankData']
            for row in rank_data:
                score_list = row.pop('scoreList')
                handle = str(row.pop('uid'))
                res = result.setdefault(handle, OrderedDict())
                res['member'] = handle
                res['place'] = row.pop('ranking')
                res['name'] = row.pop('userName')

                penalty = row.pop('penaltyTime') / 1000

                accepted_count = row.pop('acceptedCount')
                res['solved'] = {'solving': accepted_count}

                if self.contest.standings_kind == 'icpc':
                    res['solving'] = accepted_count
                    penalty /= 60
                    penalty_num = 1
                elif self.contest.standings_kind == 'scoring':
                    res['solving'] = row.pop('totalScore')
                    penalty_num = 3
                else:
                    raise ExceptionParseStandings('Unknown standings kind')

                res['penalty'] = self.to_time(penalty, num=penalty_num)

                res['is_team'] = row.pop('team')
                hidden_fields.add('is_team')

                info = res.setdefault('info', {})
                info['is_team'] = res['is_team']

                for k, v in row.items():
                    k = normalize_field(k)
                    if k not in res:
                        hidden_fields.add(k)
                        res[k] = v

                problems = res.setdefault('problems', {})
                for problem_info, score in zip(problem_infos, score_list):
                    if not score.pop('submit'):
                        continue
                    accepted_time = score.pop('acceptedTime') // 1000
                    penalty = accepted_time - self.contest.start_time.timestamp()
                    short = problem_info['short']
                    p = problems.setdefault(short, {})

                    is_accepted = score.pop('accepted')
                    attempts = score.pop('failedCount')

                    if is_accepted:
                        p['time_in_seconds'] = penalty

                    if self.contest.standings_kind == 'icpc':
                        p['result'] = '+' if is_accepted else '-'
                        if attempts:
                            p['result'] += str(attempts)
                        penalty /= 60
                    elif self.contest.standings_kind == 'scoring':
                        p['result'] = score.pop('score')
                        if not is_accepted:
                            p['partial'] = True

                    if is_accepted:
                        p['time'] = self.to_time(penalty, num=penalty_num, short=True)

                    first_ac = score.pop('firstBlood')
                    if first_ac:
                        p['first_ac'] = True

                    for k in 'submissionId', 'timeConsumption':
                        v = score.pop(k)
                        if v:
                            p[normalize_field(k)] = v
                if not problems:
                    result.pop(handle)

        data = fetch_page(1)
        process_page(data)

        n_pages = data['basicInfo']['pageCount']
        for page in tqdm.trange(2, n_pages + 1, desc='fetch pages'):
            data = fetch_page(page)
            process_page(data)

        ret = {
            'url': standings_url,
            'problems': problem_infos,
            'hidden_fields': list(hidden_fields),
            'result': result,
        }
        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):
        timestamp = int(timezone.now().timestamp() * 1000)

        @RateLimiter(max_calls=2, period=1)
        def fetch_profile(account):
            ret = {'handle': account.key}

            url = Statistic.API_RATING_HISTORY_URL_FORMAT_.format(resource.href(), account.key)
            url = f'{url}&_={timestamp}'
            data = REQ.get(url, return_json=True)
            if not isinstance(data, dict) or 'data' not in data:
                return False
            ret['ratings'] = data['data']

            profile_url = account.profile_url(resource)
            page, last_url = REQ.get(profile_url, return_url=True)
            if account.key not in last_url:
                return None

            mapping = {'Rating排名': 'rank'}
            matches = re.finditer(r'<[^>]*state-num[^>]*>(?P<value>[^<]*)</[^>]*>\s*<[^>]*>(?P<key>[^<]*)</[^>]*>', page)  # noqa: E501
            for match in matches:
                key = match.group('key')
                if key not in mapping:
                    continue
                value = match.group('value')
                ret[mapping[key]] = as_number(value)
            if 'rank' in ret and not isinstance(ret['rank'], int):
                ret['rank_str'] = ret.pop('rank')
            return ret

        balance = 10
        with PoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(fetch_profile, account) for account in accounts]
            for user, future in zip(users, futures):
                if pbar:
                    pbar.update()

                try:
                    data = future.result()
                except Exception:
                    data = False

                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        balance //= 2
                        if balance == 0:
                            break
                        yield {'skip': True}
                    continue
                balance += 1

                if data.pop('handle') != user:
                    raise ExceptionParseAccounts('Handle is not same')

                ret = dict(info=data)
                contest_addition_update = {}
                ratings = data.pop('ratings')
                ratings.sort(key=lambda x: x['time'])
                for rating in ratings:
                    contest_id = str(rating['contestId'])
                    update = contest_addition_update.setdefault(contest_id, OrderedDict())
                    update['_rank'] = rating['rank']
                    update['new_rating'] = round(rating['rating'])
                    update['rating_change'] = round(rating['changeValue'])
                    update['old_rating'] = update['new_rating'] - update['rating_change']
                    data['rating'] = update['new_rating']

                if contest_addition_update:
                    ret['contest_addition_update_params'] = dict(
                        update=contest_addition_update,
                        clear_rating_change=True,
                    )

                yield ret

            for future in futures:
                future.cancel()
