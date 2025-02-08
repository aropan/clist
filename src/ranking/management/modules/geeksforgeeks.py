#!/usr/bin/env python3

import json
import os
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import dateutil.parser
from ratelimiter import RateLimiter

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):

    PROFILE_DATA_URL_FORMAT = 'https://www.geeksforgeeks.org/gfg-assets/_next/data/{buildid}/user/{handle}.json'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        page = REQ.get('https://auth.geeksforgeeks.org/')
        form = REQ.form(page=page, action=None, fid='Login')
        if form:
            REQ.get('https://auth.geeksforgeeks.org/setLoginToken.php')
            page = REQ.submit_form(
                url='https://auth.geeksforgeeks.org/auth.php',
                data={
                    'user': conf.GEEKSFORGEEKS_USERNAME,
                    'pass': conf.GEEKSFORGEEKS_PASSWORD,
                },
                form=form,
            )

    def get_standings(self, users=None, statistics=None, **kwargs):

        result = {}

        @RateLimiter(max_calls=10, period=2)
        def fetch_and_process_page(page):
            url = f'https://practiceapi.geeksforgeeks.org/api/v1/contest/{self.key}/leaderboard/?page={page + 1}&type=current'  # noqa
            page = REQ.get(url)
            data = json.loads(page)

            for row in data['results']['ranks_list']:
                handle = row.pop('profile_link').rstrip('/').rsplit('/', 1)[-1]
                r = result.setdefault(handle, OrderedDict())
                name = row.pop('handle')
                if name != handle:
                    r['name'] = name
                r['member'] = handle
                r['place'] = row.pop('rank')
                r['solving'] = row.pop('score')
                last_correct_submission = row.get('last_correct_submission')
                if last_correct_submission:
                    time = dateutil.parser.parse(last_correct_submission + '+05:30')
                    delta = time - self.start_time
                    r['time'] = self.to_time(delta)
                for k, v in list(row.items()):
                    if k.endswith('_score'):
                        r[k] = row.pop(k)

            return data

        try:
            data = fetch_and_process_page(0)
        except FailOnGetResponse as e:
            if e.code == 403:
                raise ExceptionParseStandings(str(e))
            raise e
        total = data['results']['rows_count']
        per_page = len(data['results']['ranks_list'])
        if not total or not per_page:
            raise ExceptionParseStandings('empty standings')
        n_pages = (total + per_page - 1) // per_page

        with PoolExecutor(max_workers=8) as executor:
            executor.map(fetch_and_process_page, range(1, n_pages))

        ret = {
            'url': os.path.join(self.url, 'leaderboard'),
            'result': result,
        }
        return ret

    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=6, period=1)
        def fetch_profile(account):
            url = account.profile_url(resource)
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                if e.code == 308 or e.code == 500:
                    return False
                raise e
            match = re.search('"buildId":"(?P<buildid>[^"]*)"', page)
            buildid = match.group('buildid')
            url = Statistic.PROFILE_DATA_URL_FORMAT.format(buildid=buildid, handle=account.key)
            try:
                orig_data = REQ.get(url, return_json=True)
            except FailOnGetResponse as e:
                if e.code == 308 or e.code == 500:
                    return False
                raise e
            data = orig_data['pageProps']

            if data.get('__N_REDIRECT_STATUS') == 307 and (redirect := data.get('__N_REDIRECT')):
                if match := re.search('https://[^/]*geeksforgeeks.org/user/(?P<user>[^/]*)/?', redirect):
                    return {'rename': match.group('user'), 'handle': account.key}

            info = {}
            if 'userInfo' not in data:
                return False
            info = data.pop('userInfo')
            info['handle'] = data.pop('userHandle')

            contest_data = data.pop('contestData')
            if contest_data is None:
                info['contest_data'] = []
            else:
                user_contest_data = contest_data.pop('user_contest_data')
                info.update(contest_data)
                contest_data = user_contest_data.pop('contest_data')
                info.update(user_contest_data)
                info['contest_data'] = contest_data

            return info

        with PoolExecutor(max_workers=4) as executor:
            profiles = executor.map(fetch_profile, accounts)
            for user, data in zip(users, profiles):
                if pbar:
                    pbar.update()

                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                assert user == data.pop('handle')

                if 'rename' in data:
                    yield data
                    continue

                contest_addition_update = {}
                for contest_data in data.pop('contest_data'):
                    contest_key = contest_data.pop('slug')
                    update = contest_addition_update.setdefault(contest_key, OrderedDict())
                    update['rating_change'] = contest_data.pop('rating_change')
                    update['new_rating'] = contest_data.pop('display_rating')
                    update['_rank'] = contest_data.pop('rank')

                if data.get('current_rating'):
                    data['rating'] = data.pop('current_rating')

                for k in list(data.keys()):
                    if isinstance(data[k], (dict, list, tuple)):
                        data.pop(k)

                ret = {
                    'info': data,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'clear_rating_change': True,
                    },
                }

                yield ret
