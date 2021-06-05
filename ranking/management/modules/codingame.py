#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import re
import zlib
from base64 import b64decode, b64encode
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from functools import partial
from pprint import pprint
from urllib.parse import urljoin

import pytz
import tqdm
from django.core.cache import cache
from django.utils.timezone import now

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        page = REQ.get(
            self.host + 'services/Challenge/findWorldCupByPublicId',
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
            url = self.host + 'services/Leaderboards/getClashLeaderboard'
        else:
            url = self.host + 'services/Leaderboards/getFilteredChallengeLeaderboard'

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

        opening = {}
        with PoolExecutor(max_workers=8) as executor:
            hidden_fields = set()
            result = {}

            def process_data(data):
                nonlocal hidden_fields
                nonlocal result
                nonlocal opening
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

                        if 'openingDate' in league:
                            league_name = leagues_names[league['openingLeaguesCount'] - 1]
                            opening[league_name] = {
                                'title': f'Presumably the opening of the {league_name.title()} League',
                                'date': league['openingDate'] / 1000,
                            }

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

                    stat = (statistics or {}).get(handle)
                    if stat:
                        for field in ['codinpoints']:
                            if field in stat and field not in r:
                                r[field] = stat[field]

            process_data(data)

            if len(data['users']) >= 1000:
                fetch_data = partial(get_leaderboard, url, "LANGUAGE")
                for data in tqdm.tqdm(executor.map(fetch_data, languages), total=len(languages), desc='languages'):
                    process_data(data)

                fetch_data = partial(get_leaderboard, url, "COUNTRY")
                for data in tqdm.tqdm(executor.map(fetch_data, countries), total=len(countries), desc='countries'):
                    process_data(data)

        if self.end_time > now():
            hidden_fields.extend(['created', 'updated'])

        standings = {
            'url': standings_url,
            'result': result,
            'fields_types': {'updated': ['timestamp'], 'created': ['timestamp']},
            'hidden_fields': hidden_fields,
            'info_fields': ['_league', '_challenge', '_has_versus', '_opening'],
            '_league': leagues,
            '_challenge': challenge,
            '_opening': list(sorted(opening.values(), key=lambda o: o['date'])),
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

        if challenge.get('type') == 'BATTLE':
            standings['_has_versus'] = {'enable': True}

        return standings

    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        def fetch_ratings(user, account):
            handle = account.info.get('profile_url', {}).get('public_handle')
            if not handle:
                return user, False, None

            try:
                url = urljoin(resource.profile_url, '/services/CodinGamer/findCodingamePointsStatsByHandle')
                points_stats = json.loads(REQ.get(url, post=f'["{handle}"]', content_type='application/json'))

                url = urljoin(resource.profile_url, '/services/CodinGamer/getMyConsoleInformation')
                infos = json.loads(REQ.get(url, post=f'["{user}"]', content_type='application/json'))
            except FailOnGetResponse as e:
                if e.code == 404:
                    return user, None, None
                return user, False, None

            hist = points_stats['codingamePointsRankingDto'].pop('rankHistorics', None)
            info = points_stats.pop('codingamer')
            info.setdefault('points', {}).update(points_stats.pop('codingamePointsRankingDto'))
            info.update({k: v for k, v in points_stats.items() if not isinstance(v, list)})

            if hist is not None:
                dates = hist.pop('dates')
                rating_data = []
                prev_rating = None
                n_x_axis = resource.info['ratings']['chartjs']['n_x_axis']
                size = max(len(dates) // n_x_axis, 1)
                for offset in range(0, len(dates), size):
                    chunk = list(range(offset, min(len(dates), offset + size)))
                    ratings = [hist['points'][idx] for idx in chunk]
                    new_rating = round(sum(ratings) / len(ratings), 2)
                    st = chunk[0]
                    fn = chunk[-1]
                    r = {
                        'timestamp': dates[fn],
                        'new_rating': new_rating,
                        'name': (f'{st + 1}' if st == fn else f'{st + 1}-{fn + 1}') + f' of {len(dates)}',
                        'rank_rating': hist['ranks'][fn],
                        'place': f"{hist['ranks'][fn]:,}",
                        'total': f"{hist['totals'][fn]:,}",
                    }
                    if prev_rating is not None:
                        r['rating_change'] = round(new_rating - prev_rating, 2)
                    prev_rating = new_rating
                    rating_data.append(r)

                rating_data_str = json.dumps(rating_data)
                rating_data_zip = zlib.compress(rating_data_str.encode('utf-8'))
                rating_data_b64 = b64encode(rating_data_zip).decode('ascii')
                info['_rating_data'] = rating_data_b64

                if rating_data:
                    info.update({
                        'rating': rating_data[-1]['new_rating'],
                        'rank_rating': rating_data[-1]['rank_rating'],
                    })

            ratings = {}
            challenges = infos.get('challenges', [])
            for challenge in challenges:
                rating = ratings.setdefault(challenge['publicId'], {})
                rating['codinpoints'] = challenge['points']
            return user, info, ratings

        with PoolExecutor(max_workers=8) as executor:
            for user, info, ratings in executor.map(fetch_ratings, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue
                info = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': ratings,
                        'by': 'key',
                        'clear_rating_change': True,
                    },
                }
                yield info

    def get_versus(self, statistic, use_cache=True):
        url = self.host + 'services/gamesPlayersRanking/findLastBattlesByAgentId'
        agent_id = statistic.addition.get('agent_id')
        user_id = statistic.addition.get('user_id')

        if use_cache:
            cache_key = f'codingame__versus_data__{user_id}'
            if cache_key in cache:
                return True, cache.get(cache_key)

        data = json.loads(REQ.get(url, post=f'[{agent_id}, null]', content_type='application/json'))
        if not data:
            url = self.host + 'services/Leaderboards/getCodinGamerChallengeRanking'
            data = json.loads(REQ.get(url, post=f'[{user_id},"{self.key}",null]', content_type='application/json'))
            agent_id = data['agentId']
            try:
                url = self.host + 'services/gamesPlayersRanking/findLastBattlesByAgentId'
                data = json.loads(REQ.get(url, post=f'[{agent_id}, null]', content_type='application/json'))
            except FailOnGetResponse as e:
                return False, str(e)
        if not data:
            return False, 'Not found versus data'

        stats = {}
        my = stats.setdefault(str(user_id), defaultdict(int))
        for gidx, game in zip(reversed(range(len(data))), data):
            if not game.get('done'):
                continue
            for player in game['players']:
                if player['userId'] != user_id:
                    continue
                for opponent in game['players']:
                    if opponent['userId'] == user_id:
                        continue
                    stat = stats.setdefault(str(opponent['userId']), defaultdict(int))

                    players = sorted([player, opponent], key=lambda p: p['position'])
                    game_info = {
                        'url': self.host + f'/replay/{game["gameId"]}',
                        'index': gidx + 1,
                        'game_id': game["gameId"],
                        'players': ' vs '.join(f'{p.get("nickname","")}#{p["position"] + 1}' for p in players),
                    }
                    stat['total'] += 1
                    my['total'] += 1
                    if player['position'] == opponent['position']:
                        result = 'draw'
                    else:
                        result = 'win' if player['position'] < opponent['position'] else 'lose'
                    game_info['result'] = result
                    stat[result] += 1
                    my[result] += 1
                    my.setdefault('games', []).append(game_info)
                    stat.setdefault('games', []).append(game_info)
        cache_time_seconds = 300
        results = {
            'stats': stats,
            'games': {
                'fields': ['index', 'players', 'game_id'],
            },
            'cache_time': (now() + timedelta(seconds=cache_time_seconds)).timestamp(),
        }
        if use_cache:
            cache.set(cache_key, results, timeout=cache_time_seconds)
        return True, results

    @staticmethod
    def get_rating_history(rating_data, stat, resource, date_from=None, date_to=None):
        rating_data_zip = b64decode(rating_data.encode('ascii'))
        rating_data_str = zlib.decompress(rating_data_zip).decode('utf-8')
        rating_data = json.loads(rating_data_str)

        ret = []
        for data in rating_data:
            data['date'] = datetime.utcnow().fromtimestamp(data['timestamp'] / 1000).replace(tzinfo=pytz.utc)
            data['date_format'] = '%b %-d, %Y'
            ret.append(data)
        return ret


def run(*args):

    from clist.models import Contest
    from ranking.models import Statistics
    contest = Contest.objects.get(key='spring-challenge-2021')
    qs = Statistics.objects.filter(contest=contest, account__name="aropan").order_by('place_as_int')
    for statistic in qs:
        status, data = Statistic(contest=contest).get_versus(statistic, use_cache=False)
        if status:
            pprint(data.pop('stats', None))
        pprint(data)
