# -*- coding: utf-8 -*-

import re
import json
import requests
from time import time, sleep
from hashlib import sha512
from pprint import pprint
from urllib.parse import urlencode
from string import ascii_lowercase
from random import choice
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.management.modules import conf


API_KEYS = conf.CODEFORCES_API_KEYS
DEFAULT_API_KEY = API_KEYS[API_KEYS['__default__']]


def _query(
    method,
    params,
    api_key=DEFAULT_API_KEY,
    prev_time_queries={},
    api_url_format='https://codeforces.com/api/%s'
):
    url = api_url_format % method
    key, secret = api_key
    params = dict(params)

    params.update({
        'time': int(time()),
        'apiKey': key,
        'lang': 'en',
    })

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
        delta = max(2 - (time() - times[0]), 0)
        sleep(delta)
        times.clear()

    md5_file_cache = url
    for k in ('apiSig', 'time', ):
        md5_file_cache = re.sub('%s=[0-9a-z]+' % k, '', md5_file_cache)
    times.append(time())
    page = REQ.get(url, md5_file_cache=md5_file_cache)
    times[-1] = time()
    return json.loads(page)


class Statistic(BaseModule):

    def __init__(self, contest=None, **kwargs):
        if contest is not None:
            super().__init__(
                name=contest.title,
                url=contest.url,
                key=contest.key,
                standings_url=contest.standings_url,
                start_time=contest.start_time,
                end_time=contest.end_time,
            )
        else:
            super().__init__(**kwargs)

        cid = self.key
        if ':' in cid:
            cid, api = cid.split(':', 1)
            self.api_key = api.split(':') if ':' in api else API_KEYS[api]
        else:
            self.api_key = DEFAULT_API_KEY
        if not re.match('^[0-9]+$', cid):
            raise InitModuleException(f'Contest id {cid} should be number')
        self.cid = cid

    def get_standings(self, users=None, statistics=None):
        year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
        season = f'{year}-{year + 1}'

        is_gym = '/gym/' in self.url
        result = {}

        for unofficial in [False, True]:
            params = {
                'contestId': self.cid,
                'showUnofficial': str(unofficial).lower(),
            }
            if users:
                params['handles'] = ';'.join(users)

            try:
                data = _query(
                    method='contest.standings',
                    params=params,
                    api_key=self.api_key,
                )
            except FailOnGetResponse as e:
                if getattr(e.args[0], 'code', None) == 400:
                    return {'action': 'delete'}
                raise ExceptionParseStandings(e.args[0])

            if data['status'] != 'OK':
                raise ExceptionParseStandings(data['status'])

            contest_type = data['result']['contest']['type'].upper()
            duration_seconds = data['result']['contest'].get('durationSeconds')

            result_problems = data['result']['problems']
            problems_info = OrderedDict()
            for p in result_problems:
                d = {'short': p['index'], 'name': p['name']}
                if 'points' in p:
                    d['full_score'] = p['points']
                elif contest_type == 'IOI':
                    d['full_score'] = 100
                problems_info[d['short']] = d

            grouped = any('teamId' in row['party'] for row in data['result']['rows'])
            for row in data['result']['rows']:
                party = row['party']

                if is_gym and not party['members']:
                    is_ghost_team = True
                    name = party['teamName']
                    party['members'] = [{
                        'handle': f'{name} {season}',
                        'name': name,
                    }]
                else:
                    is_ghost_team = False

                for member in party['members']:
                    if is_gym:
                        upsolve = False
                    else:
                        upsolve = party['participantType'] != 'CONTESTANT'
                        if unofficial != upsolve:
                            continue

                    handle = member['handle']

                    r = result.setdefault(handle, OrderedDict())
                    r['member'] = handle
                    if 'room' in party:
                        r['room'] = str(party['room'])

                    r.setdefault('participant_type', []).append(party['participantType'])

                    if is_ghost_team:
                        r['name'] = member['name']
                        r['_no_update_name'] = True
                    elif grouped and (not upsolve and not is_gym or 'name' not in r):
                        r['name'] = ', '.join(m['handle'] for m in party['members'])
                        if 'teamId' in party:
                            r['team_id'] = party['teamId']
                            r['name'] = f"{party['teamName']}: {r['name']}"
                        r['_no_update_name'] = True

                    hack = row['successfulHackCount']
                    unhack = row['unsuccessfulHackCount']

                    problems = r.setdefault('problems', {})
                    for i, s in enumerate(row['problemResults']):
                        k = result_problems[i]['index']
                        points = float(s['points'])

                        n = s.get('rejectedAttemptCount')
                        if n is not None and contest_type == 'ICPC' and points + n > 0:
                            points = f'+{"" if n == 0 else n}' if points > 0 else f'-{n}'

                        u = upsolve
                        if s['type'] == 'FINAL' and (points or n):
                            if not points:
                                points = f'-{n}'
                            p = {'result': points}
                            if contest_type == 'IOI':
                                full_score = problems_info[k].get('full_score')
                                if full_score:
                                    p['partial'] = points < full_score
                            if 'bestSubmissionTimeSeconds' in s:
                                time = s['bestSubmissionTimeSeconds']
                                if time > duration_seconds:
                                    u = True
                                else:
                                    time /= 60
                                    p['time'] = '%02d:%02d' % (time / 60, time % 60)
                            a = problems.setdefault(k, {})
                            if u:
                                a['upsolving'] = p
                            else:
                                a.update(p)

                    if row['rank'] and not upsolve:
                        r['place'] = row['rank']
                        r['solving'] = row['points']
                        if contest_type == 'ICPC':
                            r['penalty'] = row['penalty']
                            r['solving'] = int(round(r['solving']))

                    if hack or unhack:
                        r['hack'] = {
                            'title': 'hacks',
                            'successful': hack,
                            'unsuccessful': unhack,
                        }

        try:
            params.pop('showUnofficial')
            data = _query(
                method='contest.ratingChanges',
                params=params,
                api_key=self.api_key,
            )
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
        except FailOnGetResponse:
            pass

        def to_score(x):
            return (1 if x.startswith('+') or float(x) > 0 else 0) if isinstance(x, str) else x

        def to_solve(x):
            return not x.get('partial', False) and to_score(x.get('result', 0)) > 0

        for r in result.values():
            upsolving = 0
            solving = 0
            upsolving_score = 0

            for a in r['problems'].values():
                if 'upsolving' in a and to_solve(a['upsolving']) > to_solve(a):
                    upsolving_score += to_score(a['upsolving']['result'])
                    upsolving += to_solve(a['upsolving'])
                else:
                    solving += to_solve(a)
            r.setdefault('solving', 0)
            r['upsolving'] = upsolving_score
            if abs(solving - r['solving']) > 1e-9 or abs(upsolving - r['upsolving']) > 1e-9:
                r['solved'] = {
                    'solving': solving,
                    'upsolving': upsolving,
                }

        standings = {
            'result': result,
            'url': (self.url + '/standings').replace('contests', 'contest'),
            'problems': list(problems_info.values()),
            'options': {
                'fixed_fields': [('hack', 'Hacks')],
            },
        }
        return standings

    @staticmethod
    def get_users_infos(users, pbar=None):
        handles = ';'.join(users)

        len_limit = 1000
        if len(handles) > len_limit:
            s = 0
            for i in range(len(users)):
                s += len(users[i])
                if s > len_limit:
                    return Statistic.get_users_infos(users[:i], pbar) + Statistic.get_users_infos(users[i:], pbar)

        removed = []
        while True:
            try:
                handles = ';'.join(users)
                data = _query(method='user.info', params={'handles': handles})
                break
            except FailOnGetResponse as e:
                page = e.args[0].read()
                data = json.loads(page)
                if data['status'] == 'FAILED' and data['comment'].startswith('handles: User with handle'):
                    handle = data['comment'].split()[-3]
                    response = requests.head(f'https://codeforces.com/profile/{handle}')
                    location = response.headers['Location']
                    target = location.split('/')[-1]
                    if location.endswith('//codeforces.com/'):
                        index = users.index(handle)
                        removed.append((index, users[index]))
                        users.pop(index)
                    else:
                        users[users.index(handle)] = target
                else:
                    raise NameError(f'data = {data}')
        if pbar is not None:
            pbar.update(len(users))
        if data['status'] != 'OK':
            raise ValueError(f'status = {data["status"]}')

        ret = data['result']
        for index, user in removed:
            ret.insert(index, None)
            users.insert(index, user)

        assert len(ret) == len(users)
        for data, user in zip(ret, users):
            if data and data['handle'].lower() != user.lower():
                raise ValueError(f'Do not match handle name for user = {user} and data = {data}')
        return ret


if __name__ == '__main__':
    pprint(Statistic(url='https://codeforces.com/contest/1119/', key='1119').get_result('tourist'))
    pprint(Statistic(url='https://codeforces.com/contest/1270/', key='1270').get_result('CodeMazz'))
    pprint(Statistic(url='https://codeforces.com/contest/1200/', key='1200').get_result('hloya_ygrt'))
    pprint(Statistic(url='https://codeforces.com/contest/1200/', key='1200').get_result('rui-de'))
    pprint(Statistic(url='https://codeforces.com/contest/1164/', key='1164').get_result('abisheka'))
    pprint(Statistic(url='https://codeforces.com/contest/1202', key='1202').get_result('kmjp'))
    pprint(Statistic(url='https://codeforces.com/contest/1198', key='1198').get_result('yosupo'))
    pprint(Statistic(url='https://codeforces.com/contest/1198', key='1198').get_result('tourist'))
    pprint(Statistic(url='https://codeforces.com/contest/1160/', key='1160').get_result('Rafbill'))
    pprint(Statistic(url='https://codeforces.com/contest/1/', key='1').get_result('spartac'))
    pprint(Statistic(url='https://codeforces.com/contest/1250/', key='1250').get_result('maroonrk'))
    pprint(Statistic(url='https://codeforces.com/contest/1250/', key='1250').get_result('sigma425'))
