#!/usr/bin/env python3

import html
import json
import math
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urljoin

import arrow
import pytz
from django.core.cache import cache
from django.utils.timezone import now
from tqdm import tqdm

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        page = REQ.get('https://cups.online/en/')
        data_profile = re.search('data-profile="(?P<value>[^"]*)"', page).group('value')
        if data_profile:
            data_profile = json.loads(html.unescape(data_profile))
        else:
            csrf_token = REQ.get_cookie('csrftoken', domain_regex='cups.online')
            page = REQ.get(
                url='https://cups.online/api_v2/login/',
                post=f'{{"email":"{conf.CUPS_EMAIL}","password":"{conf.CUPS_PASSWORD}"}}',
                headers={
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrf_token,
                },
            )

    @staticmethod
    def _get_task_id(key):
        data = REQ.get('/api_v2/contests/battles/?page_size=100500', return_json=True)
        for dcontest in data['results']:
            for dround in dcontest['rounds']:
                if str(dround['id']) == key:
                    return dround['tasks'][0]['id']

    def get_standings(self, users=None, statistics=None):
        slug = self.info.get('parse').get('slug')
        period = self.info.get('parse').get('round', {}).get('round_status', 'past')
        standings_url = urljoin(self.url, f'/results/{slug}?roundId={self.key}&period={period}')

        iter_time_delta = timedelta(hours=3)
        is_running = self.start_time < now() < self.end_time + iter_time_delta or not statistics
        is_raic = bool(re.search(r'^Code.*[0-9]{4}.*\[ai\]', self.name))
        is_final = is_raic and bool(re.search('финал|final', self.name, re.I))
        is_round = is_raic and (is_final or bool(re.search('раунд|round', self.name, re.I)))
        is_long = self.end_time - self.start_time > timedelta(days=60)

        query_params = f'?period={period}&page_size=500&round={self.key}'
        api_standings_url = urljoin(self.url, f'/api_v2/contests/{slug}/result/{query_params}')
        result = OrderedDict()
        while api_standings_url:
            data = REQ.get(api_standings_url, return_json=True, ignore_codes={404})

            if 'results' not in data:
                raise ExceptionParseStandings(f'response = {data}')

            for row in data['results']:
                r = OrderedDict()
                r['place'] = row.pop('rank')
                user = row.pop('user')
                r['member'] = user['login']
                if user.get('cropping'):
                    avatar_url = urljoin(api_standings_url, user['cropping'])
                    r['info'] = {'avatar_url': avatar_url}
                names = [user.get(field) for field in ('first_name', 'last_name') if user.get(field)]
                if names:
                    r['name'] = ' '.join(names)
                r['solving'] = row.pop('score')

                result[r['member']] = r

            api_standings_url = data.get('next')

        cache_key = f'cups_online__get_statistics__{self.key}'
        if not statistics:
            cache.delete(cache_key)
        if is_raic and (not is_running or cache_key in cache):
            for r in result.values():
                stat = (statistics or {}).get(r['member'])
                if stat:
                    for k in self.info.get('fields', {}):
                        if k in {'info', 'name', 'advance'}:
                            continue
                        if k not in r and k in stat:
                            r[k] = stat[k]

        eps = 1e-12
        battles_cache = cache.get(cache_key, set())
        task_id = self._get_task_id(self.key)
        if is_running and task_id:
            page_size = 108

            def fetch_battle(page=None):
                url = f'/api_v2/battles/task/{task_id}?page_size={page_size}'
                if page:
                    url += f'&page={page}'
                data = REQ.get(url, return_json=True)
                return data

            num_workers = 10
            with PoolExecutor(max_workers=num_workers) as executor, tqdm() as pbar:
                futures = []
                stop = False
                page = 1
                n_pages = None
                last_found_created_at = None
                while not stop and (n_pages is None or futures and page <= n_pages):
                    for _ in range(2):
                        if n_pages is not None and page + len(futures) > n_pages or len(futures) >= 2 * num_workers:
                            break
                        futures.append(executor.submit(fetch_battle, page + len(futures)))

                    future = futures.pop(0)
                    data = future.result()
                    n_pages = (data['totals'] + page_size - 1) // page_size
                    found = False
                    created_at = None
                    for battle in data['results']:
                        created_at = arrow.get(battle['created_at'])
                        created_at_timestamp = created_at.timestamp
                        if last_found_created_at is None:
                            last_found_created_at = created_at
                        if not battle['is_ranked'] or battle['id'] in battles_cache or not battle['battle_results']:
                            continue
                        battles_cache.add(battle['id'])
                        found = True
                        last_found_created_at = created_at

                        battle_result = battle['battle_results']
                        n_players = len(battle_result)

                        for i in range(n_players):
                            handle = battle_result[i]['user']['login']
                            if handle not in result:
                                continue
                            r = result[handle]

                            solution = battle_result[i]['solution']
                            if 'solution_id' not in r or (
                                solution['id'] != r['solution_id'] and created_at_timestamp > r['last_battle']
                            ):
                                r['solution_id'] = solution['id']
                                r['solution_external_id'] = solution['external_id']
                                r['last_battle'] = created_at_timestamp
                                r['first_battle'] = created_at_timestamp
                                r['language_id'] = solution['language']['id']
                                r['language'] = solution['language']['name']
                                r['games_number'] = 0
                                r['total_scores'] = 0
                                r['total_places'] = 0
                            if r['solution_id'] == solution['id']:
                                r['first_battle'] = min(r['first_battle'], created_at_timestamp)
                                r['last_battle'] = max(r['last_battle'], created_at_timestamp)

                            points = 0
                            for j in range(n_players):
                                if i == j:
                                    continue
                                delta = battle_result[i]['score'] - battle_result[j]['score']
                                if abs(delta) < eps:
                                    points += 1
                                elif delta > 0:
                                    points += 2
                            place = n_players - points / 2

                            r.setdefault('total_games', 0)
                            r.setdefault('games_number', r['total_games'])

                            if is_round or solution['id'] == r['solution_id']:
                                r['games_number'] += 1
                                r['total_scores'] += battle_result[i]['score']
                                r['total_places'] += place
                            r['total_games'] += 1

                            if is_round:
                                r.setdefault('total_points', 0)
                                r['total_points'] += points

                    if not found and (created_at is None or last_found_created_at - created_at > iter_time_delta):
                        stop = True

                    pbar.update()
                    page += 1
            cache.set(cache_key, battles_cache, timeout=timedelta(hours=6).total_seconds())

        if is_raic and task_id:
            for r in result.values():
                if not r.get('games_number'):
                    continue
                r['average_score'] = r['total_scores'] / r['games_number']
                r['average_place'] = r['total_places'] / r['games_number']

        if is_round and task_id:
            for r in result.values():
                if not math.isclose(r['solving'], r['total_points']):
                    r['leaderboard_points'] = round(r['solving'])
                if r.get('games_number') == r.get('total_games'):
                    r.pop('games_number', None)
                if not r.get('total_games'):
                    r['solving'] = 0
                else:
                    r['solving'] = r['total_points'] / r['total_games']
                    r['average_points'] = r['solving']

            if is_running:
                ordered = sorted(list(result.values()), key=lambda r: r['solving'], reverse=True)
                last_score = None
                last_rank = None
                for rank, row in enumerate(ordered, start=1):
                    if last_score is None or row['solving'] < last_score - eps:
                        last_score = row['solving']
                        last_rank = rank
                    result[row['member']]['place'] = last_rank

        ret = {
            'url': standings_url,
            'result': result,
            'fields_types': {'first_battle': ['timestamp'], 'last_battle': ['timestamp']},
            'hidden_fields': ['average_points', 'solution_id', 'solution_external_id', 'language_id',
                              'total_scores', 'total_places', 'last_battle', 'first_battle'],
            'info_fields': ['_has_versus'],
        }

        if is_round and not self.info.get('advance'):
            match = re.search('Round (?P<round>[12])', self.name)
            if match:
                threshold = [300, 50][int(match.group('round')) - 1]
                ret['advance'] = {'filter': [{'threshold': threshold, 'operator': 'le', 'field': 'place'}]}

        if is_raic and is_running and not is_long:
            ret['timing_statistic_delta'] = timedelta(minutes=10)

        if is_raic and task_id:
            ret['_has_versus'] = {'enable': True}

        if is_final and not is_running:
            ret['options'] = {
                'medals': [
                    {'name': 'gold', 'count': 1},
                    {'name': 'silver', 'count': 1},
                    {'name': 'bronze', 'count': 1},
                    {'name': 'honorable', 'count': 3},
                ]
            }

        return ret

    def get_versus(self, statistic, use_cache=True):
        if use_cache:
            cache_key = f'cups_online__versus_data__{statistic.pk}'
            if cache_key in cache:
                return True, cache.get(cache_key)

        _ = Statistic()  # init cookies
        task_id = self._get_task_id(statistic.contest.key)
        if task_id is None:
            return False, 'Not found task_id'

        member = statistic.account.key
        stats = {}
        my = stats.setdefault(member, defaultdict(int))

        page = 0
        page_size = 108
        total = None
        index = 0
        solution_id = None
        stop = False
        seen = set()
        while not stop and (total is None or page * page_size < total):
            page += 1
            url = f'/api_v2/battles/task/{task_id}?page={page}&page_size={page_size}&search={member.encode("utf-8")}'
            data = REQ.get(url, return_json=True)
            total = data['totals']
            stop = True

            for dbattle in data['results']:
                if not dbattle['is_ranked']:
                    continue
                if dbattle['id'] in seen:
                    continue
                seen.add(dbattle['id'])

                url = dbattle['visualizer_url']
                url += f'?replay=/api_v2/battles/{dbattle["id"]}/get_result_file/'
                players = []
                for dresult in dbattle['battle_results']:
                    handle = dresult['user']['login']
                    client_id = dresult['solution']['external_id']
                    url += f'&player-names={handle}&client-ids={client_id}'
                    players.append({
                        'score': dresult['score'],
                        'handle': handle,
                        'solution_id': client_id,
                    })
                url = urljoin(REQ.last_url, url)

                players.sort(reverse=True, key=lambda p: p['score'])
                last = None
                rank = None
                me = None
                for place, player in enumerate(players, start=1):
                    if player['score'] != last:
                        rank = place
                        last = player['score']
                    player['position'] = rank
                    if player['handle'] == member:
                        me = player
                if not me or solution_id is not None and solution_id != me['solution_id']:
                    continue
                solution_id = me['solution_id']
                stop = False

                index += 1
                delta = 0
                for opponent in players:
                    if opponent['handle'] == member:
                        continue
                    stat = stats.setdefault(opponent['handle'], defaultdict(int))

                    game_info_players = ' vs '.join(
                        f'{p["handle"]}#{p["position"]} ({round(p["score"], 1)})'
                        for p in players
                        if p['handle'] in {opponent['handle'], member}
                    )
                    game_info = {
                        'url': url,
                        'index': index,
                        'game_id': dbattle['id'],
                        'players': game_info_players,
                    }
                    if me['position'] == opponent['position']:
                        result = 'draw'
                    else:
                        result = 'win' if me['position'] < opponent['position'] else 'lose'
                    game_info['result'] = result
                    stat['total'] += 1
                    stat['total_scores'] += me['score']
                    stat['total_deltas'] += me['score'] - opponent['score']
                    stat[result] += 1
                    stat.setdefault('games', []).append(game_info)
                    if result == 'win':
                        delta += 1
                    elif result == 'lose':
                        delta -= 1

                if delta > 0:
                    result = 'win'
                elif delta < 0:
                    result = 'lose'
                else:
                    result = 'draw'
                my['total'] += 1
                my[result] += 1

                game_info['result'] = result
                game_info = dict(game_info)
                game_info['players'] = ' vs '.join(
                    f'{p["handle"]}#{p["position"]} ({round(p["score"], 1)})'
                    for p in players
                )
                my.setdefault('games', []).append(game_info)

        fields = OrderedDict()
        for r in stats.values():
            if 'total_scores' in r:
                r['average_score'] = r['total_scores'] / r['total']
                r['average_delta'] = r['total_deltas'] / r['total']
                fields['average_score'] = True
                fields['average_delta'] = True

        cache_time_seconds = 300
        results = {
            'stats': stats,
            'games': {'fields': ['index', 'players', 'game_id']},
            'fields': list(fields.keys()),
            'cache_time': (now() + timedelta(seconds=cache_time_seconds)).timestamp(),
        }
        if use_cache:
            cache.set(cache_key, results, timeout=cache_time_seconds)

        return True, results

    @staticmethod
    def get_rating_history(rating_data, stat, resource, date_from=None, date_to=None):
        ret = []
        old_rating = None
        for data in rating_data:
            date = datetime.utcnow().fromtimestamp(data['time']).replace(tzinfo=pytz.utc)
            new_rating = round(data['score'], 2)
            hist = {
                'name': stat['name'],
                'date': date,
                'new_rating': new_rating,
                'date_format': '%H:%M, %b %-d, %Y',
            }
            if 'place' in data and 'total' in data:
                hist['place'] = data['place']
                hist['total'] = data['total']
            if old_rating is not None:
                hist['rating_change'] = round(new_rating - old_rating, 2)
            old_rating = new_rating
            ret.append(hist)

        return ret
