#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import json
import itertools
from collections import OrderedDict
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://csacademy.com/contest/scoreboard_state/?contestId={key}'
    API_STANDINGS_URL_FORMAT_ = '{url}scoreboard/'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        if not self.key.isdigit():
            return {'action': 'delete'}

        self.cid = int(self.key)

        standings_url = self.API_STANDINGS_URL_FORMAT_.format(**self.__dict__)

        headers = {'x-requested-with': 'XMLHttpRequest'}
        page = REQ.get(standings_url, headers=headers)
        data = json.loads(page)

        if 'error' in data:
            if data['error'].get('message') in ['Object not found', 'Invalid rights, not allowed']:
                return {'action': 'delete'}
            raise ExceptionParseStandings(page)

        for contest in data['state']['Contest']:
            if contest['id'] == self.cid:
                break
        else:
            raise ExceptionParseStandings(f'Not found contest with id = {self.key}')

        tasks = {
            t['id']: {
                'code': str(t['id']),
                'name': str(t['longName']),
                'full_score': t['pointsWorth'],
            }
            for t in data['state']['contesttask']
        }
        problems_info = OrderedDict([(str(tid), tasks[tid]) for tid in contest['taskIds']])

        url = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        page = REQ.get(url, headers=headers)
        data = json.loads(page)

        users_by_id = {user['id']: user for user in data['state']['publicuser'] if user.get('username')}

        page = REQ.get(self.url, headers={'x-requested-with': ''})
        match = re.search('src="(?P<url>[^"]*PublicState[^"]*)"', page)
        page = REQ.get(match.group('url'))
        match = re.search(r'"country":\s*(?P<data>\[[^\]]*\])', page)
        countries = json.loads(match.group('data'))
        countries = {c['id']: c for c in countries}

        result = {}
        for r in data['state']['contestuser']:
            user = users_by_id.get(r.pop('userId'))
            if not r.pop('numSubmissions') or r.pop('contestId') != self.cid or not user:
                continue
            handle = user['username']
            if users and handle not in users:
                continue

            row = result.setdefault(handle, OrderedDict())

            row['name'] = user['name']
            if user.get('rating'):
                row['info'] = {'rating': int(user['rating'])}
            if user.get('countryId'):
                row['country'] = countries[user['countryId']]['isoCode']
                row['country_name'] = countries[user['countryId']]['name']

            row['member'] = handle
            if r.get('penalty'):
                row['penalty'] = int(round(r.pop('penalty'), 0))
            solving = 0

            solved = 0
            problems = row.setdefault('problems', {})
            for k, prob in r.pop('scores').items():
                k = str(k)
                p = problems.setdefault(k, {})

                n = prob['numSubmissions']
                if contest['scoreType'] == 1 and prob['score']:
                    p['result'] = prob['score'] * problems_info[k]['full_score']
                    p['n_submissions'] = n
                    p['partial'] = prob['score'] < 1
                    solving += p['result']
                    solved += 1
                elif prob['score']:
                    p['result'] = f'+{"" if n == 1 else n - 1}'
                    solving += problems_info[k]['full_score']
                    solved += 1
                else:
                    p['result'] = f'-{n}'

                if 'scoreTime' in prob:
                    p['time'] = self.to_time(prob['scoreTime'] - contest['startTime'])

            row['solving'] = solving
            row['solved'] = {'solving': solved}

            if 'oldRating' in r:
                row['old_rating'] = int(r['oldRating'])
                row['new_rating'] = int(r['rating'])

        ranks = [((-r['solving'], r.get('penalty')), r['member']) for r in result.values()]
        prev = None
        rank = None
        for index, (s, k) in enumerate(sorted(ranks), start=1):
            if not prev or prev != s:
                rank = index
                prev = s
            result[k]['place'] = rank

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statistic = Statistic(name='42', url='https://csacademy.com/contest/fii-code-2020-round-2/', key='62344')
    standings = statistic.get_standings('aropan')
    result = standings.pop('result')
    pprint(list(itertools.islice(result.items(), 0, 10)))
    pprint(standings)
    statistic = Statistic(name='42', url='https://csacademy.com/contest/fii-code-2020-round-1/', key='61564')
    standings = statistic.get_standings('aropan')
    result = standings.pop('result')
    pprint(list(itertools.islice(result.items(), 0, 10)))
    pprint(standings)
