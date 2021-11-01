# -*- coding: utf-8 -*-

import collections
import json
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack
from time import sleep
from urllib.parse import urljoin

from ratelimiter import RateLimiter
from tqdm import tqdm

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    DELAY = 1
    MAX_WORKERS = 8

    @staticmethod
    def get(url):
        n_attemps = 0
        while True:
            try:
                Statistic.DELAY *= 0.9
                Statistic.DELAY = max(0.5, min(Statistic.DELAY, 10))
                sleep(Statistic.DELAY)
                page = REQ.get(url)
                break
            except FailOnGetResponse as e:
                n_attemps += 1
                if e.code == 429 and n_attemps < 10:
                    Statistic.DELAY *= 1.5
                    continue
                raise e
        return page

    def get_standings(self, users=None, statistics=None):

        standings_url = self.url.rstrip('/') + '/leaderboard'

        per_page = 100
        if '/contests/' in self.url:
            api_standings_url_format = standings_url.replace('/contests/', '/rest/contests/')
            api_standings_url_format += '?offset={offset}&limit={limit}&include_practice=true'
        elif '/competitions/' in self.url:
            url = self.host + f'api/hrw/resources/{self.key}?include=leaderboard'
            page = REQ.get(url)
            data = json.loads(page)
            entry_id = data['included'][0]['id']
            api_standings_url_format = self.host + f'api/hrw/resources/leaderboards/{entry_id}/leaderboard_entries'
            api_standings_url_format += '?page[limit]={limit}&page[offset]={offset}'
        else:
            raise ExceptionParseStandings(f'Unusual url = {self.url}')

        @RateLimiter(max_calls=1, period=2)
        def fetch_page(page):
            offset = (page - 1) * per_page
            url = api_standings_url_format.format(offset=offset, limit=per_page)
            page = Statistic.get(url)
            data = json.loads(page)
            return data

        result = {}
        hidden_fields = set()
        schools = dict()

        def process_data(data):
            rows = data['models'] if 'models' in data else data['data']

            school_ids = set()
            for r in rows:
                if isinstance(r.get('attributes'), dict):
                    r = r['attributes']

                def get(*fields):
                    for f in fields:
                        if f in r:
                            return r.pop(f)

                handle = get('hacker', 'name')
                if handle is None:
                    continue
                row = result.setdefault(handle, collections.OrderedDict())
                row['member'] = handle
                score = get('score', 'solved_challenges')
                if score is None:
                    score = get('percentage_score') * 100
                row['solving'] = score
                row['place'] = get('rank', 'leaderboard_rank')
                time = get('time_taken', 'time_taken_seconds')
                if time:
                    row['time'] = self.to_time(time, 3)

                country = get('country')
                if country:
                    row['country'] = country

                avatar_url = get('avatar')
                if avatar_url:
                    row['info'] = {'avatar_url': avatar_url}

                for k, v in r.items():
                    if k not in row and v is not None:
                        row[k] = v
                        hidden_fields.add(k)

                if statistics and handle in statistics:
                    stat = statistics[handle]
                    for k in ('old_rating', 'rating_change', 'new_rating'):
                        if k in stat:
                            row[k] = stat[k]

                if 'school_id' in row and row['school_id'] not in schools:
                    school_ids.add(row['school_id'])

            if school_ids:
                query = ','.join(school_ids)
                url = self.host + f'community/v1/schools?page[limit]={len(school_ids)}&filter[unique_id]={query}'
                page = REQ.get(url)
                data = json.loads(page)
                for s in data['data']:
                    schools[s['id']] = s['attributes']['name']

            for row in result.values():
                if 'school_id' in row and 'school' not in row:
                    row['school'] = schools[row['school_id']]

        try:
            data = fetch_page(1)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e
        process_data(data)

        total = data['meta']['record_count'] if 'meta' in data else data['total']
        n_pages = (total - 1) // (per_page) + 1

        with ExitStack() as stack:
            executor = stack.enter_context(PoolExecutor(max_workers=Statistic.MAX_WORKERS))
            pbar = stack.enter_context(tqdm(total=n_pages - 1, desc='getting pages'))

            for data in executor.map(fetch_page, range(1, n_pages + 1)):
                process_data(data)
                pbar.set_postfix(delay=f'{Statistic.DELAY:.5f}', refresh=False)
                pbar.update()

        hidden_fields.discard('school')

        standings = {
            'result': result,
            'hidden_fields': list(hidden_fields),
            'url': standings_url,
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=Statistic.MAX_WORKERS, period=1)
        def fetch_profile(user):
            url = urljoin(resource.url, f'/rest/contests/master/hackers/{user}/profile')
            try:
                page = Statistic.get(url)
            except FailOnGetResponse as e:
                code = e.code
                if code == 404:
                    return None
                return {}
            data = json.loads(page)
            if not data:
                return None
            data = data['model']

            url = urljoin(resource.url, f'/rest/hackers/{user}/rating_histories_elo')
            page = Statistic.get(url)
            data['ratings'] = json.loads(page)['models']
            return data

        with PoolExecutor(max_workers=Statistic.MAX_WORKERS) as executor:
            profiles = executor.map(fetch_profile, users)
            for user, account, data in tqdm(zip(users, accounts, profiles), total=len(users), desc='getting users'):
                if not data:
                    if data is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue

                data = {k: v for k, v in data.items() if v is not None and (v or not isinstance(v, str))}
                assert user == data['username']

                info = {}

                country = data.pop('country', None)
                if country:
                    info['country'] = country

                school = data.pop('school', None)
                if school:
                    info['school'] = school

                avatar_url = data.pop('avatar', None)
                if avatar_url:
                    info['avatar_url'] = avatar_url

                info['data'] = data

                contest_addition_update = {}

                ratings = data.pop('ratings', None)
                if ratings:
                    for category in ratings:
                        if category['category'].lower() == 'algorithms':
                            break
                    else:
                        category = None

                    if category:
                        for rating in category['events']:
                            update = contest_addition_update.setdefault(rating['contest_name'],
                                                                        collections.OrderedDict())
                            new_rating = int(rating['rating'])
                            if 'rating' in info:
                                update['old_rating'] = info['rating']
                                update['rating_change'] = new_rating - info['rating']
                            update['new_rating'] = new_rating
                            info['rating'] = new_rating

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': 'title',
                        'clear_rating_change': True,
                    },
                }

                yield ret
