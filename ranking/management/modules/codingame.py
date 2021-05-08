#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import re
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from functools import partial

import tqdm

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):

        urlinfo = urllib.parse.urlparse(self.url)
        host = f'{urlinfo.scheme}://{urlinfo.netloc}/'

        page = REQ.get(
            host + 'services/Challenge/findWorldCupByPublicId',
            post=f'["{self.key}", null]',
            content_type='application/json',
        )
        data = json.loads(page)
        challenge = data.get('challenge', {})
        clash_hubs = challenge.get('clashHubs')

        def get_leaderboard(url, column="", value=""):
            active = 'true' if column else 'false'
            filt = f'{{"active":{active},"column":"{column}","filter":"{value}"}}'
            if clash_hubs:
                post = f'[1,{filt},null,true,"global",{clash_hubs[0]["clashHubId"]}]'
            else:
                post = f'["{self.key}",null,"global",{filt}]'
            page = REQ.get(url, post=post, content_type='application/json')
            data = json.loads(page)
            return data

        if clash_hubs:
            url = host + 'services/Leaderboards/getClashLeaderboard'
        else:
            url = host + 'services/Leaderboards/getFilteredChallengeLeaderboard'

        data = get_leaderboard(url)

        standings_url = os.path.join(self.url, 'leaderboard')

        countries = None
        leagues_names = None
        page = REQ.get(standings_url)
        matches = re.finditer(r'<script[^>]*src="(?P<js>[^"]*static[^"]*\.codingame[^"]*\.js)"[^>]*>', page)
        for match in matches:
            page = REQ.get(match.group('js'), detect_charsets=None)
            if countries is None:
                m = re.search(r'const t={EN:(?P<countries>\[{id:"[^"]*",name:"[^"]*"},.*?}]),[A-Z]{2}:', page)
                if m:
                    countries = m.group('countries')
                    countries = countries.replace('id:', '"id":')
                    countries = countries.replace('name:', '"name":')
                    countries = json.loads(countries)
                    countries = [c['id'] for c in countries]
            if leagues_names is None:
                m = re.search(r'N=(?P<array>\[(?:"[^"]*",?)+\])', page)
                if m:
                    leagues_names = [league.title() for league in json.loads(m.group('array'))]
            if countries is not None and leagues_names is not None:
                break
        if countries is None:
            raise ExceptionParseStandings('not found countries')

        def get_league_name(league):
            nonlocal leagues_names
            if leagues_names is None:
                raise ExceptionParseStandings('not found leagues_names')
            index = league['divisionCount'] - league['divisionIndex'] - 1 + league.get('divisionOffset', 0)
            number = index - len(leagues_names) + 2
            return f'{leagues_names[-1]} {number}' if number >= 1 else leagues_names[index]

        leagues = data.get('leagues')
        if leagues:
            leagues = [get_league_name(league) for league in reversed(leagues.values())]

        languages = list(data.get('programmingLanguages', {}).keys())

        with PoolExecutor(max_workers=8) as executor:
            hidden_fields = set()
            result = {}

            def process_data(data):
                nonlocal hidden_fields
                nonlocal result
                for row in data['users']:
                    if 'codingamer' not in row:
                        continue
                    info = row.pop('codingamer')
                    row.update(info)

                    info['profile_url'] = {'public_handle': info.pop('publicHandle')}
                    handle = str(info.pop('userId'))
                    if handle in result:
                        continue
                    r = result.setdefault(handle, OrderedDict())
                    r['member'] = handle
                    r['place'] = row.pop('rank')
                    r['info'] = info

                    if 'league' in row:
                        league = row.pop('league')
                        r['league'] = get_league_name(league)
                        r['league_rank'] = row.pop('localRank')

                    for field, out in (
                        ('score', 'solving'),
                        ('programmingLanguage', 'language'),
                        ('clashes_count', 'clashes_count'),
                        ('pseudo', 'name'),
                        ('countryId', 'country'),
                        ('company', 'company'),
                        ('school', 'school'),
                    ):
                        if field in row:
                            r[out] = row.pop(field)
                            if field in ('school', 'company'):
                                hidden_fields.add(field)

                    if 'updateTime' in row:
                        row['updated'] = row.pop('updateTime') / 1000
                    if 'creationTime' in row:
                        row['created'] = row.pop('creationTime') / 1000

                    row.pop('public_handle', None)
                    row.pop('test_session_handle', None)
                    row.pop('avatar', None)
                    for k, v in row.items():
                        if k not in r:
                            r[k] = v
                            hidden_fields.add(k)

            process_data(data)

            if len(data['users']) >= 1000:
                fetch_data = partial(get_leaderboard, url, "LANGUAGE")
                for data in tqdm.tqdm(executor.map(fetch_data, languages), total=len(languages), desc='languages'):
                    process_data(data)

                fetch_data = partial(get_leaderboard, url, "COUNTRY")
                for data in tqdm.tqdm(executor.map(fetch_data, countries), total=len(countries), desc='countries'):
                    process_data(data)

        standings = {
            'url': standings_url,
            'result': result,
            'fields_types': {'updated': ['timestamp'], 'created': ['timestamp']},
            'hidden_fields': hidden_fields,
            'info_fields': ['_league'],
            '_league': leagues,
            'options': {
                'fixed_fields': [
                    ('league', 'league'),
                    ('league_rank', 'league_rank'),
                    ('language', 'Language'),
                    ('clashes_count', 'clashes_count'),
                    ('created', 'Submit Time'),
                ],
                'medals': [
                    {'name': 'gold', 'count': 1},
                    {'name': 'silver', 'count': 1},
                    {'name': 'bronze', 'count': 1},
                ],
            },
        }

        return standings
