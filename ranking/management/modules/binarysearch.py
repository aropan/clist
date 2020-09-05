#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from tqdm import tqdm

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.common.locator import Locator


class Statistic(BaseModule):
    API_ROOM_URL_FORMAT_ = 'https://api.binarysearch.io/rooms/{channelSlug}?slug={slug}'
    API_RANKING_URL_FORMAT_ = 'https://api.binarysearch.io/rooms/{id}/sessions/{sid}/leaderboards?page={page}'
    API_PROFILE_URL_FORMAT_ = 'https://api.binarysearch.io/users/{user}/profile'

    def get_standings(self, users=None, statistics=None):
        per_page = 10

        url = self.API_ROOM_URL_FORMAT_.format(**self.info['parse'])
        page = REQ.get(url)
        room_data = json.loads(page)
        results = OrderedDict()
        problems_info = OrderedDict()

        for session in room_data['sessions']:
            total = len(session['players'])
            problems_ids = []
            for idx, problems_set in enumerate(session['questionsets']):
                problem = problems_set['question']
                info = {
                    'code': str(problem['id']),
                    'name': problem['title'],
                    'url': f'{self.url}?questionsetIndex={idx}'
                }
                if problem.get('difficulty') is not None:
                    info['full_score'] = problem['difficulty'] + 3
                problems_info[info['code']] = info
                problems_ids.append(info['code'])

            def fetch_results(page):
                url = self.API_RANKING_URL_FORMAT_.format(id=self.key, sid=session['id'], page=page)
                page = REQ.get(url)
                data = json.loads(page)
                return data

            if users or users is None:
                with PoolExecutor(max_workers=8) as executor:
                    n_page = (total - 1) // per_page + 1

                    rank = 0
                    idx = 0
                    last = None
                    for data in tqdm(executor.map(fetch_results, range(n_page)), total=n_page, desc='getting results'):
                        for row in data['leaders']:
                            idx += 1
                            score = (row['score'], row['durationTime'])
                            if last != score:
                                rank = idx
                                last = score

                            handle = row.pop('username')
                            if users and handle not in users:
                                continue
                            r = results.setdefault(handle, {})
                            r['member'] = handle
                            r['solving'] = row.pop('score')
                            r['place'] = rank
                            r['penalty'] = self.to_time(row.pop('durationTime'))

                            solved = 0
                            problems = r.setdefault('problems', {})
                            for code, duration, attempts in zip(
                                problems_ids, row.pop('durationTimes'), row.pop('attempts')
                            ):
                                p = problems.setdefault(code, {})
                                if duration:
                                    p['result'] = '+'
                                    p['time'] = self.to_time(duration)
                                    p['binary'] = True
                                    if attempts > 1:
                                        p['penalty_score'] = attempts - 1
                                    solved += 1
                                elif attempts:
                                    p['result'] = f'-{attempts}'
                            r['solved'] = {'solving': solved}
                            r['info'] = {'stat': row.pop('stat')}
        standings = {
            'result': results,
            'problems': list(problems_info.values()),
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_profile(user):
            nonlocal stop
            if stop:
                return False
            url = Statistic.API_PROFILE_URL_FORMAT_.format(user=user)
            page = REQ.get(url)
            data = json.loads(page)
            return data

        with PoolExecutor(max_workers=8) as executor, Locator() as locator:
            stop = False
            profiles = executor.map(fetch_profile, users)
            for user, account, data in tqdm(zip(users, accounts, profiles), total=len(users), desc='getting users'):
                if stop:
                    break
                if not data:
                    yield {'info': None}
                    return
                data = data['user']
                assert user == data['username']
                data = {k: v for k, v in data.items() if k == 'stat' or not isinstance(v, (dict, list))}
                location = data.get('location')
                if (
                    location and
                    location.lower() != 'planet earth' and
                    (not account.country or account.info.get('country') != location)
                ):
                    country = locator.get_country(location)
                    if country:
                        data['country'] = country
                yield {'info': data}
