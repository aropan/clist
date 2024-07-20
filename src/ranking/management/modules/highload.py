#!/usr/bin/env python3

from urllib.parse import urljoin

from clist.templatetags.extras import get_item
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    API_STANDINGS_URL_FORMAT_ = '/api/timed_competitions/leaderboard/v1/'

    def get_standings(self, users=None, statistics=None, **kwargs):
        api_standings_url = urljoin(self.url, Statistic.API_STANDINGS_URL_FORMAT_)

        standings_data = REQ.get(
            api_standings_url,
            post={'competition_id': get_item(self, 'info.parse.contest.id'),
                  'round_id': get_item(self, 'info.parse.round.id')},
            return_json=True,
        )

        if get_item(standings_data, 'result') != 'OK':
            raise ExceptionParseStandings(standings_data)

        result = {}
        for row_data in get_item(standings_data, 'data'):
            member = str(row_data.pop('user_id'))
            row = result.setdefault(member, {'member': member})
            row['name'] = row_data.pop('user_name')
            row['solving'] = row_data.pop('score')
            row['place'] = row_data.pop('position')
            info = row.setdefault('info', {})
            info['avatar'] = row_data.pop('user_avatar_url')
            info.update(row_data)

        standings = {'result': result}
        return standings
