# -*- coding: utf-8 -*-

import json
import os
import re
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha512
from random import choice
from string import ascii_lowercase
from time import sleep, time
from urllib.parse import urlencode, urljoin, urlparse

import pytz
from django.db.models import Min

from clist.models import Problem
from clist.templatetags.extras import as_number, get_division_problems, get_problem_short, is_solved, slug
from pyclist.middleware import RedirectException
from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, UNCHANGED, BaseModule, parsed_table, utc_now
from ranking.management.modules.excepts import (ExceptionParseAccounts, ExceptionParseStandings, FailOnGetResponse,
                                                InitModuleException)
from ranking.utils import create_upsolving_statistic
from utils.aes import AESModeOfOperation
from utils.strings import strip_tags
from utils.timetools import parse_datetime

API_KEYS = conf.CODEFORCES_API_KEYS
DEFAULT_API_KEY = API_KEYS[API_KEYS['__default__']]
SUBDOMAIN = ''


def api_query(
    method,
    params,
    api_key=DEFAULT_API_KEY,
    prev_time_queries={},
    api_url_format='https://codeforces.com/api/%s',
):
    url = api_url_format % method
    key, secret = api_key
    params = dict(params)

    params.update({'time': int(time()), 'apiKey': key})
    params.setdefault('lang', 'en')

    url_encode = '&'.join(('%s=%s' % (k, v) for k, v in sorted(params.items())))

    api_sig_prefix = ''.join(choice(ascii_lowercase) for x in range(6))
    api_sig = '%s/%s?%s#%s' % (
        api_sig_prefix,
        method,
        url_encode,
        secret,
    )
    params['apiSig'] = api_sig_prefix + sha512(api_sig.encode('utf8')).hexdigest()
    url += '?' + urlencode(params)

    times = prev_time_queries.setdefault((key, secret), [])
    if len(times) == 5:
        delta = max(4 - (time() - times[0]), 0)
        sleep(delta)
        times.clear()

    md5_file_cache = url
    for k in ('apiSig', 'time', ):
        md5_file_cache = re.sub('%s=[0-9a-z]+' % k, '', md5_file_cache)
    times.append(time())

    for attempt in reversed(range(5)):
        try:
            ret = REQ.get(url, md5_file_cache=md5_file_cache, return_json=True, last_info=True)
            times[-1] = time()
        except FailOnGetResponse as e:
            if e.code == 503 and attempt:
                sleep(1)
                continue
            try:
                ret = json.loads(e.response)
            except json.decoder.JSONDecodeError:
                ret = {'status': str(e)}
            ret['code'] = e.code
        except json.decoder.JSONDecodeError as e:
            if attempt:
                sleep(1)
                continue
            ret = {'status': str(e)}
        break
    ret.setdefault('status', 'EMPTY')
    return ret


def _get(url, *args, return_url=False, **kwargs):
    if SUBDOMAIN and SUBDOMAIN not in url:
        url = url.replace('://codeforces.', '://%scodeforces.' % SUBDOMAIN, 1)
    page, last_url = REQ.get(url, *args, return_url=True, **kwargs)
    if 'document.cookie="RCPC="+toHex(slowAES.decrypt(c,2,a,b))+";' in page:
        matches = re.findall(r'(?P<var>[a-z]+)=toNumbers\("(?P<value>[^"]*)"\)', page)
        variables = {}
        for variable, value in matches:
            variables[variable] = [int(value[i:i + 2], 16) for i in range(0, len(value), 2)]

        size = len(variables['a'])
        ret = AESModeOfOperation().decrypt(variables['c'], None, 2, variables['a'], size, variables['b'])
        rcpc = ''.join(('0' if x < 16 else '') + hex(x)[2:] for x in map(ord, ret))
        REQ.add_cookie('RCPC', rcpc)

        result = re.search('document.location.href="(?P<url>[^"]*)"', page)
        url = result.group('url')
        page, last_url = REQ.get(url, *args, return_url=True, **kwargs)
        REQ.save_cookie()
    return (page, last_url) if return_url else page


class Statistic(BaseModule):
    OFFICIAL_PARTICIPANT_TYPES = {'CONTESTANT'}
    PARTICIPANT_TYPES = OFFICIAL_PARTICIPANT_TYPES | {'OUT_OF_COMPETITION'}
    SUBMISSION_URL_FORMAT_ = '{url}/submission/{sid}'
    PROBLEM_STATUS_URL_FORMAT_ = '/problemset/status/{cid}/problem/{short}'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.is_spectator_ranklist = self.standings_url and 'spectator/ranklist' in self.standings_url
        self.is_blitz_cup = 'blitz-cup' in self.key and self.standings_url and '/blog/entry/' in self.standings_url
        if self.is_spectator_ranklist or self.is_blitz_cup:
            return

        cid = self.key
        if ':' in cid:
            cid, api = cid.split(':', 1)
            self.api_key = api.split(':') if ':' in api else API_KEYS[api]
        else:
            self.api_key = DEFAULT_API_KEY
        if not re.match('^[0-9]+$', cid):
            raise InitModuleException(f'Contest id {cid} should be number')
        self.cid = cid

    def get_standings_from_html(self, url=None, with_exception=True):
        url = urljoin(self.url, url or self.standings_url)
        page = _get(urljoin(url, '?lang=en'))
        regex = '''<table[^>]*standings[^>]*>.*?</table>'''
        match = re.search(regex, page, re.DOTALL)
        if not match:
            if with_exception:
                raise ExceptionParseStandings('Not found table')
            return
        html_table = match.group(0)
        mapping = {
            '#': 'place',
            'Who': 'name',
            '=': 'solving',
            'Penalty': 'penalty',
        }
        table = parsed_table.ParsedTable(html_table, header_mapping=mapping)

        season = self.get_season()

        problems_info = OrderedDict()
        result = {}
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in r.items():
                ks = k.split()
                if len(ks[0]) == 1:
                    short = ks[0]
                    problems_info.setdefault(short, {'short': short})
                    if len(ks) == 2 and (full_score := as_number(ks[1], force=True)):
                        problems_info[short]['full_score'] = full_score
                    if v.value:
                        p = problems.setdefault(short, {})
                        v = v.value
                        if ' ' in v:
                            v, p['time'] = v.split()
                        p['result'] = v
                elif k == 'name':
                    f = v.column.node.xpath('.//img[@class="standings-flag"]/@title')
                    if f:
                        row['country'] = f[0]
                    a = v.column.node.xpath('.//a')
                    if not a:
                        row[k] = v.value
                        row['member'] = row['name'] + ' ' + season
                    else:
                        for el in a:
                            href = el.attrib.get('href')
                            if not href:
                                continue
                            key, val = href.strip('/').split('/')
                            if key == 'team':
                                row['name'] = el.text
                                row['team_id'] = val
                                row['_account_url'] = urljoin(url, href)
                            elif key == 'profile':
                                row.setdefault('members', []).append(val)
                elif v.value:
                    if k == 'penalty':
                        row[k] = int(v.value)
                    elif v.value:
                        row[k] = v.value

            if 'solving' not in row:
                continue

            if 'members' in row:
                if 'team_id' in row:
                    row['_members'] = [{'account': m} for m in row['members']]
                for member in row.pop('members'):
                    result[member] = deepcopy(row)
                    result[member]['member'] = member
            else:
                result[row['member']] = row

        standings = {
            'result': result,
            'url': url,
            'problems': list(problems_info.values()),
        }

        match = re.search('<span class="contest-status">([^<]*)</span>', page)
        if match:
            standings['status'] = slug(match.group(1))

        return standings

    @staticmethod
    def process_submission(submission, result, upsolve, contest, with_binary=False):
        contest_url = contest.url.replace('contests', 'contest')

        info = {
            'submission_id': submission['id'],
            'url': Statistic.SUBMISSION_URL_FORMAT_.format(url=contest_url, sid=submission['id']),
            'external_solution': True,
        }

        if 'verdict' in submission:
            v = submission['verdict'].upper()
            info['verdict'] = ''.join(s[0].upper() for s in v.split('_')) if len(v) > 3 else v.upper()

        if 'programmingLanguage' in submission:
            info['language'] = submission['programmingLanguage']

        if 'creationTimeSeconds' in submission:
            info['submission_time'] = submission['creationTimeSeconds']

        is_accepted = info.get('verdict') == 'OK'
        if not is_accepted and 'passedTestCount' in submission:
            info['test'] = submission['passedTestCount'] + 1

        if with_binary:
            info['binary'] = is_accepted

        party = submission['author']
        for member in party['members']:
            if 'handle' not in member:
                continue
            handle = member['handle']
            if handle not in result:
                continue
            r = result[handle]
            problems = r.setdefault('problems', {})
            k = submission['problem']['index']
            p = problems.setdefault(k, {})

            if upsolve:
                p = p.setdefault('upsolving', {})

            update_result = 'result' not in p or is_solved(p['result']) < is_accepted
            if (
                update_result or
                'submission_id' not in p or
                p['submission_id'] > info['submission_id'] and is_accepted
            ):
                if update_result:
                    info['result'] = '+' if is_accepted else '-'
                p.update(info)
                info['updated'] = True
            r = as_number(p.get('result'), force=True)
            p['partial'] = not is_accepted and p.get('partial', True) and r and r > 0

        info['is_accepted'] = is_accepted
        return info

    def get_blitz_cup_standings_from_html(self):
        url = urljoin(self.standings_url, '?lang=ru')
        page = _get(url)
        content = re.search(r'<div[^>]*class="content"[^>]*>.*?</div>', page, re.DOTALL).group(0)
        matches = re.finditer('<(?P<tag>li|h3)>(?P<content>.*?)</(?:li|h3)>', content)
        result = {}
        problem_infos = {}
        member_rounds = defaultdict(list)
        elimination_rounds = []
        delay = None
        now = utc_now()
        for match in matches:
            tag = match.group('tag')
            if tag == 'h3':
                contest_day = strip_tags(match.group('content'))
                continue
            match = match.group('content')
            members = re.findall(r'<a[^>]*href="[^"]*profile/([^"]*)"[^>]*>', match)

            winners_of = re.search(r'winners?\s*of\s*(\d+)\s*and\s*(\d+)', match, re.IGNORECASE)
            if winners_of and len(members) < 2:
                members = []
                for winner_of in [winners_of.group(1), winners_of.group(2)]:
                    winner_of = int(winner_of) - 1
                    members.extend(elimination_rounds[winner_of]['advancing_members'])

            if not members:
                continue

            if re.search(r'\brematch\b', match, re.IGNORECASE):
                elimination_round = elimination_rounds.pop()
                for member in elimination_round['advancing_members']:
                    member_rounds[member].pop()
                for member in elimination_round['members']:
                    result[member]['problems'].pop(str(elimination_round['problem']), None)

            if scoreboard := re.search(r'<a[^>]*href="(?P<url>[^"]*/spectator/ranklist/[^"]*)"[^>]*>', match):
                scoreboard_url = scoreboard.group('url')
                match_result = self.get_standings_from_html(scoreboard_url, with_exception=False)
                scoreboard_url = urljoin(self.url, scoreboard_url)
                scoreboard_status = (match_result or {}).get('status') or ''
            else:
                match_result = None
                scoreboard_url = None

            if contest_time_match := re.search(r'<a[^>]*class="contest-time"[^>]*href="(?P<url>[^"]*)"[^>]*>', match):
                contest_time = parse_datetime(contest_time_match.group('url')).timestamp()
            elif contest_time and (contest_time_match := re.search(r'[^;()]*UTC\s*[+-][^;()]*', match)):
                contest_time = f'{str(self.start_time.year)} {contest_day} {contest_time_match.group()}'
                contest_time = parse_datetime(contest_time).timestamp()
            else:
                contest_time = None
            if contest_time and contest_time > now.timestamp():
                if delay is None or contest_time - now.timestamp() < delay:
                    delay = contest_time - now.timestamp()

            advancing_members = members.copy()
            for member in members:
                row = result.setdefault(member, {'member': member})
                problems = row.setdefault('problems', {})

                short = str(len(problems) + 1)
                if short not in problem_infos:
                    problem_infos[short] = {'short': short}

                problem = problems.setdefault(short, {'blitz_round': match_result})
                if contest_time:
                    problem['start_time'] = int(contest_time)
                if scoreboard_url:
                    problem['standings_url'] = scoreboard_url
                if match_result:
                    round_result = match_result['result'][member]
                    score = str(round_result['solving'])
                    for opponent in members:
                        if opponent == member:
                            continue
                        opponent_result = match_result['result'][opponent]
                        score = f'{score} : {opponent_result["solving"]}'
                    if 'running' in scoreboard_status:
                        problem['result'] = f'?{score}'
                        delay = timedelta(minutes=5).total_seconds()
                    else:
                        problem['status'] = score
                        problem['binary'] = as_number(round_result['place']) == 1
                        problem['result'] = int(problem['binary'])
                        if not problem['binary']:
                            advancing_members.remove(member)
                else:
                    problem['result_verdict'] = 'hidden'

            round_idx = len(elimination_rounds)
            previous_rounds = []
            for member in members:
                if member not in member_rounds:
                    continue
                if (member_round := member_rounds[member][-1]) not in previous_rounds:
                    previous_rounds.append(member_round)
            elimination_round = {
                'round': int(short),
                'problem': short,
                'members': members,
                'match': match_result,
                'previous': previous_rounds,
                'start_time': contest_time,
                'scoreboard_url': scoreboard_url,
                'advancing_members': advancing_members,
            }
            elimination_rounds.append(elimination_round)
            for member in advancing_members:
                member_rounds[member].append(round_idx)

        def bracket_dfs(elimination_round, indices):
            for previous in elimination_round.pop('previous'):
                bracket_dfs(elimination_rounds[previous], indices)
            indices[elimination_round['round']] += 1
            elimination_round['index'] = indices[elimination_round['round']]
            elimination_round['n_rows'] = 2 ** (elimination_round['round'] - 1)
        bracket_dfs(elimination_rounds[-1], defaultdict(int))
        elimination_rounds.sort(key=lambda r: (r['round'], r['index']))

        for row in result.values():
            row['solving'] = sum(1 for p in row['problems'].values() if p.get('binary'))
            row['order'] = (row['solving'], len(row['problems']))

        last_score, last_rank = None, None
        for rank, row in enumerate(sorted(result.values(), key=lambda x: x['order'], reverse=True), start=1):
            score = row.pop('order')
            if last_score != score:
                last_score = score
                last_rank = rank
            row['place'] = last_rank

        problems = list(problem_infos.values())
        round_names = ['Final', 'Semifinal', 'Quarterfinal']
        for index, problem in enumerate(reversed(problems), start=0):
            problem['name'] = round_names[index] if index < len(round_names) else f'R{2 ** (index + 1)}'
            problem['ignore'] = True

        standings = {
            'result': result,
            'problems': problems,
            'elimination_tournament_info': {
                'rounds': elimination_rounds,
            }
        }
        if delay is not None:
            standings['timing_statistic_delta'] = timedelta(seconds=delay)
            standings['force_timing_statistic_delta'] = True

        return standings

    def get_standings(self, users=None, statistics=None, **kwargs):
        now = utc_now()

        def parse_points_info(points_info):
            if not points_info:
                return None
            return float(points_info.split('/')[0])

        if self.is_spectator_ranklist:
            return self.get_standings_from_html()

        if self.is_blitz_cup:
            return self.get_blitz_cup_standings_from_html()

        contest_url = self.url.replace('contests', 'contest')
        standings_url = contest_url.rstrip('/') + '/standings'

        participant_types = self.PARTICIPANT_TYPES.copy()
        is_gym = '/gym/' in self.url
        if is_gym:
            participant_types.add('VIRTUAL')

        limited = self.end_time + timedelta(days=100) < now
        limited_count = 100000

        result = {}

        domain_users = {}
        if '_domain_users' in self.info:
            for user in self.info['_domain_users']:
                user = deepcopy(user)
                domain_users[user.pop('login')] = user

        problems_info = OrderedDict()
        all_special = True
        for unofficial in [True]:
            params = {
                'contestId': self.cid,
                'showUnofficial': str(unofficial).lower(),
            }
            if users:
                params['handles'] = ';'.join(users)
            if limited:
                params['count'] = limited_count

            data = api_query(method='contest.standings', params=params, api_key=self.api_key)

            if data['status'] != 'OK':
                if data.get('code') == 400:
                    return {'action': 'delete'}
                raise ExceptionParseStandings(data['status'])

            phase = data['result']['contest'].get('phase', 'FINISHED').upper()
            contest_type = data['result']['contest']['type'].upper()
            duration_seconds = data['result']['contest'].get('durationSeconds')

            result_problems = data['result']['problems']
            for p in result_problems:
                d = {'short': p['index'], 'name': p['name']}
                if 'points' in p:
                    d['full_score'] = p['points']
                tags = p.get('tags')
                if tags:
                    d['tags'] = tags
                all_special = all_special and any('special' in tag for tag in (tags or []))
                d['url'] = urljoin(standings_url.rstrip('/'), f"problem/{d['short']}")

                if not is_gym and not users:
                    status_url = self.PROBLEM_STATUS_URL_FORMAT_.format(cid=self.cid, short=d['short'])
                    status_url = urljoin(self.url, status_url)
                    try:
                        page = _get(status_url)
                        match = re.search(r'<div[^>]*>\s*(?:Problem|Задача)\s*(?P<code>[0-9A-Z]+)\s*-', page)
                    except FailOnGetResponse as e:
                        if e.code == 403:
                            match = None
                        else:
                            raise
                    if match:
                        d['code'] = match.group('code')
                        if self.cid not in d['code']:
                            d['_no_problem_url'] = True
                    elif len(self.contest.key) < 6:
                        d['code'] = f'{self.contest.key}{d["short"]}'
                        same_problems = self.resource.problem_set.filter(name=d["name"],
                                                                         start_time=self.contest.start_time)
                        min_code = same_problems.aggregate(Min('key'))['key__min']
                        if min_code:
                            d['code'] = min(min_code, d['code'])

                problems_info[d['short']] = d

            translation_params = {**params, 'lang': 'ru', 'count': 1}
            translation_data = api_query(method='contest.standings', params=translation_params, api_key=self.api_key)
            for p in translation_data['result']['problems']:
                short = p['index']
                if not (problem_info := problems_info.get(short)) or problem_info['name'] == p['name'] or not p['name']:
                    continue
                translation = problem_info.setdefault('translation', {})
                translation = translation.setdefault('ru', {})
                translation['name'] = p['name']

            grouped = any(
                'teamId' in row['party'] and row['party']['participantType'] in participant_types
                for row in data['result']['rows']
            )

            place = None
            last = None
            first_score = None
            last_score = None
            idx = 0
            teams_to_skip = set()
            for row in data['result']['rows']:
                party = row['party']

                is_ghost = row.get('ghost') or (is_gym and not party['members'])
                if is_ghost:
                    name = party['teamName']
                    party['members'] = [{
                        'handle': f'{name} {self.get_season()}',
                        'name': name,
                    }]

                for member in party['members']:
                    if 'handle' not in member:
                        continue

                    upsolve = party['participantType'] not in participant_types
                    handle = member['handle']
                    r = result.setdefault(handle, OrderedDict())
                    r['member'] = handle

                    if is_gym:
                        r['ghost'] = is_ghost
                    if 'room' in party:
                        r['room'] = as_number(party['room'])

                    r.setdefault('participant_type', []).append(party['participantType'])
                    r['_no_update_n_contests'] = not bool(participant_types & set(r['participant_type']))
                    r['_skip_medal'] = not bool(Statistic.OFFICIAL_PARTICIPANT_TYPES & set(r['participant_type']))

                    if is_ghost and member['name']:
                        r['name'] = member['name']
                        r['_no_update_name'] = True
                    elif grouped and (not upsolve and not is_gym or 'name' not in r):
                        r['name'] = ', '.join(m['handle'] for m in party['members'])
                        if 'teamId' in party:
                            r['team_id'] = party['teamId']
                            r['name'] = f"{party['teamName']}"
                            r['_members'] = [{'account': m['handle']} for m in party['members']]
                            r['_account_url'] = urljoin(self.url, '/team/' + str(r['team_id']))
                        r['_no_update_name'] = True
                    if domain_users and '=' in handle:
                        _, login = handle.split('=', 1)
                        r.update(domain_users.get(login, {}))

                    hack = row['successfulHackCount']
                    unhack = row['unsuccessfulHackCount']

                    problems = {}
                    if limited and handle in statistics:
                        problems = deepcopy(statistics[handle].get('problems', {}))
                    problems = r.setdefault('problems', problems)
                    for i, s in enumerate(row['problemResults']):
                        k = result_problems[i]['index']
                        points = float(s['points'])
                        if contest_type == 'IOI' and 'pointsInfo' in s:
                            new_points = parse_points_info(s['pointsInfo'])
                            if new_points is not None:
                                points = new_points

                        n = s.get('rejectedAttemptCount')
                        if n is not None and contest_type == 'ICPC' and points + n > 0:
                            points = f'+{"" if n == 0 else n}' if points > 0 else f'-{n}'

                        u = upsolve
                        if s['type'] == 'PRELIMINARY' and phase == 'SYSTEM_TEST':
                            p = {'result': f'?{n + 1}'}
                        elif points or n:
                            if not points:
                                points = f'-{n}'
                                n = None
                            p = {'result': points}
                            if contest_type == 'IOI':
                                full_score = problems_info[k].get('full_score')
                                if full_score:
                                    p['partial'] = points < full_score
                            elif contest_type == 'CF' and n:
                                p['penalty_score'] = n
                        else:
                            continue

                        if 'bestSubmissionTimeSeconds' in s and duration_seconds:
                            time = s['bestSubmissionTimeSeconds']
                            if time > duration_seconds:
                                u = True
                            else:
                                p['time_in_seconds'] = time
                                time /= 60
                                p['time'] = '%02d:%02d' % (time / 60, time % 60)
                        a = problems.setdefault(k, {})
                        if u:
                            a['upsolving'] = p
                        else:
                            a.update(p)

                    if row['rank'] and not upsolve:
                        score = row['points']
                        if contest_type == 'IOI' and 'pointsInfo' in row:
                            new_points = parse_points_info(row['pointsInfo'])
                            if new_points is not None:
                                score = new_points

                        if is_gym:
                            r['place'] = row['rank']
                        elif unofficial:
                            if users:
                                r['place'] = UNCHANGED
                            elif 'team_id' not in r and not (participant_types & set(r['participant_type'])):
                                r['place'] = None
                            else:
                                if 'team_id' in r:
                                    if r['team_id'] not in teams_to_skip:
                                        teams_to_skip.add(r['team_id'])
                                        idx += 1
                                else:
                                    idx += 1
                                value = (score, row.get('penalty'))
                                if last != value:
                                    last = value
                                    place = idx
                                r['place'] = place

                        if first_score is None:
                            first_score = score
                        if score:
                            last_score = score

                        r['solving'] = score
                        if contest_type == 'ICPC':
                            r['penalty'] = row['penalty']

                    if hack or unhack:
                        r['hack'] = {
                            'title': 'hacks',
                            'successful': hack,
                            'unsuccessful': unhack,
                        }

        params.pop('showUnofficial')
        params.pop('count', None)

        if not users and self.contest.end_time < now and not is_gym:
            data = api_query(method='contest.ratingChanges', params=params, api_key=self.api_key)
            if data['status'] not in ['OK', 'FAILED']:
                LOG.warning(f'Missing rating changes = {data}')
            if data and data['status'] == 'OK':
                for row in data['result']:
                    if str(row.pop('contestId')) != self.key:
                        continue
                    handle = row.pop('handle')
                    if handle not in result:
                        continue
                    r = result[handle]
                    old_rating = row.pop('oldRating')
                    new_rating = row.pop('newRating')
                    r['old_rating'] = old_rating
                    r['new_rating'] = new_rating
        elif statistics:
            for handle, row in statistics.items():
                if handle not in result:
                    continue
                for field in ('old_rating', 'new_rating'):
                    if field in row:
                        r[field] = row[field]

        params = {'contestId': self.cid}
        if users:
            array_params = []
            for user in users:
                params['handle'] = user
                array_params.append(deepcopy(params))
        elif limited:
            params['count'] = limited_count
            array_params = [params]
        else:
            array_params = [params]

        submissions = []
        for params in array_params:
            data = api_query('contest.status', params=params, api_key=self.api_key)
            if data['status'] not in ['OK', 'FAILED']:
                raise ExceptionParseStandings(data)
            if data['status'] == 'OK':
                submissions.extend(data.pop('result'))

        has_accepted = False
        for submission in submissions:
            party = submission['author']
            upsolve = party['participantType'] not in participant_types
            if (
                'relativeTimeSeconds' in submission
                and duration_seconds
                and duration_seconds < submission['relativeTimeSeconds']
            ):
                upsolve = True

            info = Statistic.process_submission(submission, result, upsolve, contest=self)

            has_accepted |= info['is_accepted']
            if contest_type == 'IOI' and info['is_accepted'] and 'points' in submission:
                k = submission['problem']['index']
                problems_info[k].setdefault('full_score', submission['points'])

        result = {
            k: v for k, v in result.items()
            if v.get('hack') or v.get('problems') or 'new_rating' in v or not v.get('_no_update_n_contests')
        }

        def to_score(x):
            return (
                (1 if x.startswith('+') or not x.startswith('-') and not x.startswith('?') and float(x) > 0 else 0)
                if isinstance(x, str) else x
            )

        def to_solve(x):
            return not x.get('partial', False) and to_score(x.get('result', 0)) > 0

        for r in result.values():
            upsolving_score = 0
            upsolving = 0
            solving = 0
            for a in r['problems'].values():
                if 'upsolving' in a and to_solve(a['upsolving']) > to_solve(a):
                    upsolving_score += to_score(a['upsolving']['result'])
                    upsolving += to_solve(a['upsolving'])
                else:
                    solving += to_solve(a)
            r.setdefault('solving', 0)
            if abs(solving - r['solving']) > 1e-9 or abs(upsolving - upsolving_score) > 1e-9:
                r['solved'] = {
                    'solving': solving,
                    'upsolving': upsolving,
                }

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
            'options': {
                'fixed_fields': [('hack', 'Hacks')],
            },
        }

        if (
            contest_type == 'IOI'
            and phase == 'FINISHED'
            and not has_accepted
            and all('full_score' not in problem for problem in problems_info.values())
            and first_score is not None
        ):
            standings['default_problem_full_score'] = 'max' if first_score > last_score else 'min'

        if re.search('^educational codeforces round', self.name, re.IGNORECASE):
            standings['options'].setdefault('timeline', {}).update({'attempt_penalty': 10 * 60,
                                                                    'challenge_score': False})
        elif re.search(r'\<div\.\s*3\>', self.name, re.IGNORECASE):
            standings['options'].setdefault('timeline', {}).update({'attempt_penalty': 10 * 60,
                                                                    'challenge_score': False})

        if phase != 'FINISHED' and self.end_time + timedelta(hours=1) > now:
            standings['timing_statistic_delta'] = timedelta(minutes=5)
        elif abs(self.end_time - now) < timedelta(minutes=15):
            standings['timing_statistic_delta'] = timedelta(minutes=10)
        elif phase == 'SYSTEM_TEST' and self.end_time + timedelta(hours=48) > now:
            standings['timing_statistic_delta'] = timedelta(minutes=15)

        if grouped:
            standings['grouped_team'] = grouped

        if problems_info and all_special:
            standings['kind'] = 'special'

        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):
        assert resource is None or 'gym' not in resource.host

        len_limit = 2000
        total_len = 0
        for i in range(len(users)):
            total_len += len(users[i])
            if total_len > len_limit:
                yield from Statistic.get_users_infos(users[:i], pbar=pbar)
                yield from Statistic.get_users_infos(users[i:], pbar=pbar)
                return

        removed = []
        last_index = 0
        orig_users = list(users)
        for _ in range(len(users) * 2):
            handles = ';'.join(users)
            data = api_query(method='user.info', params={'handles': handles})
            if data['status'] == 'OK':
                for index in range(len(users)):
                    users[index] = data['result'][index]['handle']
                break
            if (
                data['status'] == 'FAILED'
                and (match := re.search('handles: User with handle (?P<handle>.*) not found', data['comment']))
            ):
                handle = match.group('handle')
                location = REQ.geturl(f'https://{SUBDOMAIN}codeforces.com/profile/{handle}')
                index = users.index(handle)
                if urlparse(location).path.rstrip('/'):
                    target = location.rstrip('/').split('/')[-1]
                    users[index] = target
                else:
                    removed.append((index, users[index]))
                    users.pop(index)
                if pbar is not None:
                    pbar.update(index - last_index)
                    last_index = index
            else:
                raise NameError(f'data = {data}')
        else:
            raise ValueError(f'Many failed query, data = {data}')

        if pbar is not None:
            pbar.update(len(users) - last_index)

        infos = data['result']
        for index, user in removed:
            infos.insert(index, None)
            users.insert(index, user)

        assert len(infos) == len(users)

        parse_russian_name = 'CODEFORCES_PARSE_RUSSIAN_NAME' in os.environ
        for data, user, orig in zip(infos, users, orig_users):
            if data is None:
                yield {'delete': True}
                continue
            if data:
                if data['handle'].lower() != user.lower():
                    raise ValueError(f'Do not match handle name for user = {user} and data = {data}')
                if data.get('avatar', '').endswith('/no-avatar.jpg'):
                    data.pop('avatar')
                if data.get('titlePhoto', '').endswith('/no-title.jpg'):
                    data.pop('titlePhoto')
                data['name'] = ' '.join([data[f] for f in ['firstName', 'lastName'] if data.get(f)])
            info = {'info': data}

            if parse_russian_name:
                page = REQ.get(f'https://{SUBDOMAIN}codeforces.com/profile/{user}?locale=ru')
                match = re.search(
                    r'''<div style="margin-top: 0.5em;">\s*'''
                    r'''<div style="font-size: 0.8em; color: #777;">(?P<name>[^<,]*)''',
                    page,
                )
                if match:
                    data['name_ru'] = match.group('name').strip()
            else:
                info['special_info_fields'] = {'name_ru'}

            if data and data['handle'] != orig:
                info['rename'] = data['handle']
            yield info
        if parse_russian_name:
            REQ.get(f'https://{SUBDOMAIN}codeforces.com/?locale=en')

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')
        raise RedirectException()
        # page, last_url = _get(problem['url'], return_url=True)
        # if last_url != problem['url']:
        #     raise ExceptionParseStandings('Not allowed to view source code')
        # result = re.search('<pre[^>]*id="program-source-text"[^>]*class="(?P<class>[^"]*)"[^>]*>(?P<source>[^<]*)</pre>', page)  # noqa
        # if not result:
        #     raise ExceptionParseStandings('Not found source code')
        # solution = html.unescape(result.group('source'))
        # ret = {'solution': solution}
        # for c in result.group('class').split():
        #     if c.startswith('lang-'):
        #         ret['lang_class'] = c
        # return ret

    @staticmethod
    def update_submissions(account, resource, with_submissions, pagination_size, **kwargs):
        info = deepcopy(account.info.setdefault('submissions_', {}))
        info.setdefault('count', 0)
        last_id = info.setdefault('last_id', -1)

        start = 1
        count = 10000 if last_id == -1 else 1000
        if pagination_size:
            count = min(count, pagination_size)

        stop = False
        first_submission = True
        stats_caches = {}
        ret = defaultdict(int)
        while not stop:
            data = api_query(method='user.status', params={'handle': account.key, 'from': start, 'count': count})
            if 'result' not in data:
                raise ExceptionParseAccounts(data)
            submissions = data['result']
            if not submissions:
                break

            for submission in submissions:
                if last_id >= submission['id']:
                    stop = True
                    break
                info['count'] += 1

                is_testing = submission.get('verdict', '').upper() == 'TESTING'
                if is_testing:
                    info = deepcopy(account.info.setdefault('submissions_', {}))
                    first_submission = True
                    continue

                if first_submission:
                    info['last_id'] = submission['id']
                    first_submission = False

                party = submission['author']
                participant_type = party['participantType']
                upsolve = participant_type not in Statistic.PARTICIPANT_TYPES
                if not upsolve:
                    continue

                contest_id = submission.get('contestId')
                if contest_id is None:
                    continue

                if contest_id in stats_caches:
                    contest, stat = stats_caches[contest_id]
                    created = False
                else:
                    contest = resource.contest_set.filter(key=contest_id).first()
                    if contest is None:
                        continue
                    stat, created = create_upsolving_statistic(resource=resource, contest=contest, account=account)
                    stats_caches[contest_id] = contest, stat

                if 'creationTimeSeconds' in submission:
                    submission_time = datetime.fromtimestamp(submission['creationTimeSeconds'])
                    submission_time = submission_time.replace(tzinfo=pytz.utc)
                    if not account.last_submission or account.last_submission < submission_time:
                        account.last_submission = submission_time

                addition = stat.addition
                if created:
                    participant_types = addition.setdefault('participant_type', [])
                    if participant_type not in participant_types:
                        participant_types.append(participant_type)

                result = {account.key: deepcopy(addition)}
                submission_info = Statistic.process_submission(
                    submission, result, upsolve=True, contest=contest, with_binary=True)

                if with_submissions:
                    problem_short = submission['problem']['index']
                    for problem in get_division_problems(contest, addition):
                        if get_problem_short(problem) == problem_short:
                            break
                    else:
                        raise ExceptionParseAccounts('Not found problem')

                    ret.setdefault('submissions', []).append({
                        'contest': contest,
                        'problem': problem,
                        'info': submission_info,
                    })

                if not submission_info.get('updated'):
                    continue

                ret['n_updated'] += 1

                stat.addition = result[account.key]
                stat.save()

            if len(submissions) < count:
                break
            start += count

        account.info['submissions_'] = info
        account.save(update_fields=['info', 'last_submission'])

        if stats_caches:
            ret['n_contests'] = len(stats_caches)
        return ret
