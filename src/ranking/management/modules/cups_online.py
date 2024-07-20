#!/usr/bin/env python3

import html
import json
import math
import re
import urllib
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from urllib.parse import urljoin

import arrow
import pytz
from django.core.cache import cache
from django.utils.timezone import now
from tqdm import tqdm

from clist.templatetags.extras import get_problem_short
from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        urlinfo = urllib.parse.urlparse(self.resource.url)
        self.host_url = f'{urlinfo.scheme}://{urlinfo.netloc}'

        page = REQ.get('https://cups.online/en/')
        data_profile = re.search('data-profile="(?P<value>[^"]*)"', page).group('value')
        if data_profile:
            data_profile = json.loads(html.unescape(data_profile))
        else:
            csrf_token = REQ.get_cookie('csrftoken', domain_regex='cups.online')
            page = REQ.get(
                url=f'{self.host_url}/api_v2/login/',
                post=f'{{"email":"{conf.CUPS_EMAIL}","password":"{conf.CUPS_PASSWORD}"}}',
                headers={
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrf_token,
                },
            )

    def old_aicups_get_standings(self, users=None, statistics=None):
        page = REQ.get(self.standings_url, detect_charsets=True)
        tabs = re.findall('<a[^>]*data-toggle="tab">(?:<[^>]*>)*(?P<name>[^<]+)', page)
        tables = re.findall('<table[^<]*>.*?</table>', page, re.DOTALL)
        rating_name = self.info.get('_rating_name', self.name)

        for index, (tab, table) in enumerate(zip(tabs, tables), start=1):
            if tab in rating_name:
                standings_url = self.standings_url.split('#')[0] + f'#{index}'
                break
        else:
            raise ExceptionParseStandings('Not found standings table')

        table = parsed_table.ParsedTable(table)
        result = {}
        fixed_fields = []
        for row in table:
            r = OrderedDict()
            for k, v in row.items():
                if k == '#':
                    r['place'] = v.value
                elif k == 'Пользователь':
                    # find tag a with href start with "/profile/"
                    href = v.column.node.xpath('.//a[starts-with(@href, "/profile/")]/@href')
                    if len(href) != 1:
                        raise ExceptionParseStandings(f'Not found user url, url = {href}')
                    uid = re.search('([0-9]+)/?', href[0]).group(1)
                    handle = f'aicups:{uid}'
                    r['member'] = handle
                    r['name'] = re.sub(r'\s+', ' ', v.value)
                    r['info'] = {
                        'profile_url': {
                            'resource': 'aicups.ru',
                            'account': uid,
                        },
                        '_name_instead_key': True,
                    }
                    r['_name_instead_key'] = True
                elif k == 'Результат':
                    r['solving'] = v.value
                elif v.value:
                    if k == '':
                        k = 'language'
                    k = k.lower()
                    r[k] = v.value
                    if k not in fixed_fields:
                        fixed_fields.append(k)
            result[r['member']] = r

        options = {'fixed_fields': list(fixed_fields)}

        is_final = bool(re.search(r'\bФинал', self.name))
        if is_final:
            options['medals'] = [
                {'name': 'gold', 'count': 1},
                {'name': 'silver', 'count': 1},
                {'name': 'bronze', 'count': 1},
            ]

        return {
            'url': standings_url,
            'result': result,
            'options': options,
        }

    def _get_task_id(self, key):
        data = REQ.get(f'{self.host_url}/api_v2/contests/battles/?page_size=100500', return_json=True)
        for dcontest in data['results']:
            for dround in dcontest['rounds']:
                if str(dround['id']) == key and dround['tasks']:
                    return dround['tasks'][0]['id']

    def get_standings(self, users=None, statistics=None, **kwargs):
        if self.standings_url and '/aicups.ru/' in self.standings_url:
            return self.old_aicups_get_standings(users=users, statistics=statistics)

        slug = self.info.get('parse').get('slug')
        period = self.info.get('parse').get('round', {}).get('round_status', 'past')

        iter_time_delta = timedelta(hours=3)
        is_running = self.start_time < now() < self.end_time + iter_time_delta or not statistics
        is_raic = bool(re.search(r'^Code.*[0-9]{4}.*\[ai\]', self.name))
        is_final = is_raic and bool(re.search('финал|final', self.name, re.I))
        is_round = is_raic and (is_final or bool(re.search('раунд|round', self.name, re.I)))
        is_long = self.end_time - self.start_time > timedelta(days=60)

        standings_list = [
            {
                'standings_url': f'/rounds/{self.key}/leaderboard',
                'api_standings_url': f'/api_v2/round/{self.key}/fast_leaderboard/?page_size=500',
            },
            {
                'standings_url': f'/results/{slug}?roundId={self.key}&period={period}',
                'api_standings_url': f'/api_v2/contests/{slug}/result/?period={period}&page_size=500&round={self.key}',
            },
        ]

        result = OrderedDict()
        errors = []
        problems_infos = OrderedDict()

        for standings_data in standings_list:
            standings_url = urljoin(self.host_url, standings_data['standings_url'])
            api_standings_url = urljoin(self.host_url, standings_data['api_standings_url'])
            has_penalty = False
            while api_standings_url:
                data = REQ.get(api_standings_url, return_json=True, ignore_codes={404})

                if 'results' not in data:
                    errors.append(f'response = {data}')
                    break

                round_data = data.get('round')
                if round_data and not problems_infos:
                    tasks = round_data.pop('tasks')
                    for task in tasks:
                        task['code'] = str(task.pop('id'))
                        task['short'] = task.pop('order_sign', None)
                        task['full_score'] = task.pop('complete_score', None)
                        task['url'] = urljoin(self.resource.url, '/tasks/' + task['code'])
                        task = {k: v for k, v in task.items() if v is not None}
                        problems_infos[task['code']] = task

                for row in data['results']:
                    user = row.pop('user')
                    member = user.pop('login')
                    r = result.setdefault(member, OrderedDict())
                    r['member'] = member
                    r['place'] = row.pop('rank')
                    if user.get('cropping'):
                        avatar_url = urljoin(api_standings_url, user.pop('cropping'))
                        r['info'] = {'avatar_url': avatar_url, **deepcopy(user)}
                    names = [user[field] for field in ('first_name', 'last_name') if user.get(field)]
                    if names:
                        r['name'] = ' '.join(names)
                    r['solving'] = row.pop('score')
                    if row.get('passed_count') is not None:
                        solved = row.pop('passed_count')
                        if r['solving'] is None:
                            r['solving'] = solved
                        else:
                            r['solved'] = {'solving': solved}
                    if row.get('penalty_total') is not None:
                        r['penalty'] = round(row.pop('penalty_total'))
                        has_penalty |= bool(r['penalty'])

                    task_results = row.pop('task_results', [])
                    if task_results:
                        problems = r.setdefault('problems', {})
                        for task_result in task_results:
                            problem_code = str(task_result.pop('task_id'))
                            if problem_code not in problems_infos:
                                continue
                            short = get_problem_short(problems_infos[problem_code])
                            problem = problems.setdefault(short, {})
                            score = task_result.pop('score')
                            attempts = task_result.pop('attempts_number')
                            is_passed = task_result.pop('is_passed')
                            is_frozen = task_result.pop('is_frozen')
                            if is_passed and attempts is not None:
                                attempts -= 1
                            if score is None:
                                score = '?' if is_frozen else '+' if is_passed else '-'
                                score += str(attempts if attempts else '')
                                attempts = None
                            problem['result'] = score
                            if attempts:
                                problem['attempts'] = attempts
                            if not is_frozen and is_passed is not None and not is_passed:
                                problem['partial'] = True
                            time_in_seconds = task_result.pop('is_passed_time')
                            if time_in_seconds is not None:
                                problem['time'] = self.to_time(round(time_in_seconds), short=True)
                                problem['time_in_seconds'] = time_in_seconds

                api_standings_url = data.get('next')

            if not has_penalty:
                for r in result.values():
                    r.pop('penalty', None)

            if result:
                break

        if not result and errors:
            raise ExceptionParseStandings(errors)

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
                url = f'{self.host_url}/api_v2/battles/task/{task_id}?page_size={page_size}'
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
                        created_at_timestamp = created_at.timestamp()
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

        problems = list(problems_infos.values())
        problems = [p for p in problems if not p.get('hide_leaderboard')]

        ret = {
            'url': standings_url,
            'result': result,
            'fields_types': {'first_battle': ['timestamp'], 'last_battle': ['timestamp']},
            'hidden_fields': ['average_points', 'solution_id', 'solution_external_id', 'language_id',
                              'total_scores', 'total_places', 'last_battle', 'first_battle'],
            'info_fields': ['_has_versus'],
            'problems': problems,
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
            url = f'{self.host_url}/api_v2/battles/task/{task_id}?page={page}&page_size={page_size}&search={member.encode("utf-8")}'  # noqa
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
