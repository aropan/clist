# -*- coding: utf-8 -*-

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from ratelimiter import RateLimiter

from clist.templatetags.extras import get_item
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):
    _API_LEADERBOARD_URL_FORMAT = '{resource.api_url}/contest_leaderboard?slug={contest.key}&count={{count}}&page={{page}}'  # noqa
    _API_USER_DETAILS_URL_FORMAT = '{resource.api_url}/profile/user_details?uuid={handle}'
    _API_USER_RATING_DATA_URL_FORMAT = '{resource.api_url}/user_rating_data?uuid={handle}'

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.contest.is_major_kind() or get_item(self, 'info.parse.contest_type') != 'Code 360':
            return {'action': 'skip'}

        api_leaderboard_url = self._API_LEADERBOARD_URL_FORMAT.format(resource=self.resource, contest=self.contest)
        page = 1
        count = 1000

        def fetch_page(page):
            url = api_leaderboard_url.format(page=page, count=count)
            data = REQ.get(url, return_json=True)
            return data

        page = 0
        result = OrderedDict()
        while True:
            page += 1

            try:
                data = fetch_page(page)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return {'action': 'delete'}
                if e.code == 403:
                    return {'action': 'skip'}
                raise ExceptionParseStandings(e)

            users = data['data']['users']
            if not users:
                break
            for user in users:
                handle = user.pop('uuid')
                if not handle:
                    continue
                solving = user.pop('points')
                if not solving:
                    continue
                row = result.setdefault(handle, {'member': handle})
                row['place'] = user.pop('rank')
                row['solving'] = solving
                if name := user.pop('name'):
                    row['name'] = name
                info = row.setdefault('info', {})
                if image := user.pop('image'):
                    info['avatar_url'] = image
                if screen_name := user.pop('screen_name'):
                    info['screen_name'] = screen_name

                stat = (statistics or {}).get(handle)
                if stat:
                    for field in ('new_rating', 'rating_change', 'problems_solved', 'total_problems'):
                        if field in stat:
                            row[field] = stat[field]

        return {'result': result}

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_user_data(handle):
            user_data = {}
            info = user_data.setdefault('info', {})
            info['uuid'] = handle
            url = Statistic._API_USER_DETAILS_URL_FORMAT.format(resource=resource, handle=handle)
            try:
                data = REQ.get(url, return_json=True)['data']
            except FailOnGetResponse as e:
                if e.code == 404:
                    user_data['delete'] = True
                    return user_data
                raise ExceptionParseAccounts(e)

            if name := get_item(data, 'profile.name'):
                info['name'] = name
            if uuid := data.pop('uuid'):
                info['uuid'] = uuid
            if screen_name := data.pop('screen_name'):
                info['screen_name'] = screen_name
            if image := data.pop('image'):
                info['avatar_url'] = image
            extra_info = info.setdefault('extra', {})
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    continue
                extra_info[key] = value

            url = Statistic._API_USER_RATING_DATA_URL_FORMAT.format(resource=resource, handle=handle)
            data = REQ.get(url, return_json=True)['data']
            if raw_rating := data.get('current_user_rating'):
                info['raw_rating'] = raw_rating
                info['rating'] = int(raw_rating)
            if name := data.get('ranker_name'):
                info['name'] = name
            if points := data.get('ranker_points'):
                info['points'] = points

            user_rating_data = data.get('user_rating_data', [])
            contest_addition_update = {}
            last_rating = None
            for rating_data in user_rating_data:
                if 'rank' not in rating_data:
                    continue
                contest_name = rating_data['name']
                rating = rating_data['rating']
                update = contest_addition_update.setdefault(contest_name, OrderedDict())
                update['rating_change'] = rating - last_rating if last_rating is not None else None
                update['new_rating'] = rating
                update['problems_solved'] = rating_data['problems_solved']
                update['total_problems'] = rating_data['total_problems']
                update['_rank'] = rating_data['rank']
                last_rating = rating
            user_data['contest_addition_update_params'] = {
                'update': contest_addition_update,
                'by': 'title',
                'clear_rating_change': True,
                'try_fill_missed_ranks': True,
            }

            return user_data

        with PoolExecutor(max_workers=8) as executor:
            for handle, data in zip(users, executor.map(fetch_user_data, users)):
                if handle != (uuid := get_item(data, 'info.uuid')):
                    raise ExceptionParseAccounts(f'Expected {handle}, got {uuid}')
                if pbar:
                    pbar.update()
                yield data
