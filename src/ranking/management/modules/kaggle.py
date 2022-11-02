# -*- coding: utf-8 -*-

import collections
from copy import deepcopy

import dateutil.parser

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

        teams = {t['teamId']: t for t in data['teams']}

        result = {}

        for row in data['publicLeaderboard']:
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
                        row[k] = v
                handle = member['userName']
                row['member'] = handle
                result[handle] = row

        standings = {
            'fields_types': {'last_submission': ['timestamp']},
            'grouped_team': True,
            'result': result,
            'url': self.STANDING_URL_FORMAT_.format(self),
        }
        return standings
