# -*- coding: utf-8 -*-

import collections
import json
import os
import re
from copy import deepcopy
from functools import partial

import dateutil.parser
from flatten_dict import flatten

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = '{0.url}/leaderboard'
    API_STANDINGS_URL_ = 'https://www.kaggle.com/api/i/competitions.LeaderboardService/GetLeaderboard'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        standings_url = self.STANDING_URL_FORMAT_.format(self)
        try:
            REQ.get(standings_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e

        xsrf_token = REQ.get_cookie('XSRF-TOKEN', domain_regex='kaggle')

        post = '{"competitionId":' + self.key + ',"leaderboardMode":"LEADERBOARD_MODE_DEFAULT"}'
        headers = {'content-type': 'application/json', 'x-xsrf-token': xsrf_token}
        data = REQ.get(self.API_STANDINGS_URL_, post, headers=headers, return_json=True)

        if 'teams' not in data:
            raise ExceptionParseStandings('Not found teams')

        result = {}
        hidden_fields = {'public_score', 'public_rank'}

        is_leaderboard = True
        has_public_diff = False
        for leaderboard in ('privateLeaderboard', 'publicLeaderboard'):
            if not data.get(leaderboard):
                continue

            teams = {t['teamId']: t for t in deepcopy(data['teams'])}

            for row in data[leaderboard]:
                team_id = row.pop('teamId')
                r = collections.OrderedDict()
                if 'rank' in row:
                    r['place'] = row.pop('rank')
                r['solving'] = row.pop('displayScore')
                if 'medal' in row:
                    r['medal'] = row.pop('medal').lower()

                team = teams.pop(team_id)
                r['name'] = team.pop('teamName')
                r['team_id'] = team.pop('teamId')
                r['last_submission'] = dateutil.parser.parse(team.pop('lastSubmissionDate')).timestamp()
                members = team.pop('teamMembers', [])
                r['_members'] = [{'account': m['userName']} for m in members]
                for member in members:
                    row = deepcopy(r)
                    for k, v in team.items():
                        if k not in row:
                            hidden_fields.add(k)
                            row[k] = v
                    handle = member['userName']
                    if handle.startswith('del='):
                        continue

                    row['member'] = handle

                    if is_leaderboard:
                        result[handle] = row
                        continue
                    if handle not in result:
                        row.pop('place', None)
                        result[handle] = row
                        continue
                    orig = result[handle]

                    orig_place = as_number(orig.get('place'), force=True)
                    row_place = as_number(row.get('place'), force=True)
                    if orig_place is not None and row_place is not None:
                        orig['public_rank'] = row_place
                        orig['delta_rank'] = row_place - orig_place
                        has_public_diff |= row_place != orig_place

                    orig_solving = as_number(orig.get('solving'), force=True)
                    row_solving = as_number(row.get('solving'), force=True)
                    if orig_solving is not None and row_solving is not None:
                        orig['public_score'] = row_solving
                        orig['delta_score'] = orig_solving - row_solving
                        has_public_diff |= row_solving != orig_solving

            is_leaderboard = False
        if not has_public_diff:
            for row in result.values():
                row.pop('public_rank', None)
                row.pop('delta_rank', None)
                row.pop('public_score', None)
                row.pop('delta_score', None)

        standings = {
            'fields_types': {'last_submission': ['timestamp'], 'delta_rank': ['delta']},
            'hidden_fields': list(hidden_fields),
            'grouped_team': True,
            'result': result,
            'url': self.STANDING_URL_FORMAT_.format(self),
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_profile(req, handle, raise_on_error=False):
            connect_func = partial(fetch_profile, handle=handle, raise_on_error=True)
            req.proxer.set_connect_func(connect_func)

            url = resource.profile_url.format(account=handle)
            try:
                page = req.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                if raise_on_error:
                    raise e
                ret = req.proxer.get_connect_ret()
                if ret:
                    return ret
                return False
            result = re.search(r'Kaggle.State.push\((?P<data>{"userId":.*})\);', page)
            data = json.loads(result.group('data'))
            data.get('followers', {}).pop('list', None)
            data.get('following', {}).pop('list', None)
            for k, v in data.items():
                if k.endswith('Summary') and isinstance(v, dict):
                    v.pop('highlights', None)
            data = flatten(data, 'dot')
            name = data.pop('displayName')
            if name:
                data['name'] = name
            return data

        with REQ(
            with_proxy=True,
            args_proxy={
                'time_limit': 2,
                'n_limit': 50,
                'filepath_proxies': os.path.join(os.path.dirname(__file__), '.kaggle.proxies'),
            },
        ) as req:
            for user in users:
                data = fetch_profile(req, user)
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue

                assert user == data['userName']

                ret = {
                    'info': data,
                    'replace_info': True,
                }

                yield ret
