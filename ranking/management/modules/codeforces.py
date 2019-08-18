# -*- coding: utf-8 -*-

from common import REQ, BaseModule
from excepts import ExceptionParseStandings
import conf

import re
import json
from time import time, sleep
from hashlib import sha512
from pprint import pprint
from urllib.parse import urlencode
from string import ascii_lowercase
from random import choice


class Statistic(BaseModule):
    API_URL_FORMAT = 'http://codeforces.com/api/%s'
    PREV_TIME_QUERIES = {}

    API_KEYS = conf.CODEFORCES_API_KEYS

    DEFAULT_API_KEY = API_KEYS[API_KEYS['__default__']]

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        cid = self.key
        if ':' in cid:
            cid, api = cid.split(':', 1)
            self.api_key = api.split(':') if ':' in api else self.API_KEYS[api]
        else:
            self.api_key = Statistic.DEFAULT_API_KEY
        self.cid = cid

    def query(self, method, params, api_key=DEFAULT_API_KEY):
        url = Statistic.API_URL_FORMAT % method
        key, secret = api_key

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

        times = Statistic.PREV_TIME_QUERIES.setdefault((key, secret), [])
        if len(times) == 5:
            delta = 1 - (time() - times[0]) + 1e-3
            if delta > 0:
                sleep(delta)
            times = times[1:]

        md5_file_cache = url
        for k in ('apiSig', 'time', ):
            md5_file_cache = re.sub('%s=[0-9a-z]+' % k, '', md5_file_cache)
        page = REQ.get(url, md5_file_cache=md5_file_cache)
        times.append(time())
        return json.loads(page)

    def get_standings(self, users=None):
        params = {
            'contestId': self.cid,
            'showUnofficial': 'true',
        }

        if users:
            params['handles'] = ';'.join(users)

        data = self.query(
            method='contest.standings',
            params=params,
            api_key=self.api_key,
        )

        if data['status'] != 'OK':
            raise ExceptionParseStandings(data['status'])

        contest_type = data['result']['contest']['type'].upper()

        result_problems = data['result']['problems']
        problems_info = []
        for p in result_problems:
            d = {'short': p['index'], 'name': p['name']}
            if 'points' in p:
                d['full_score'] = p['points']
            problems_info.append(d)

        result = {}
        for row in data['result']['rows']:
            for member in row['party']['members']:
                handle = member['handle']
                r = result.setdefault(handle, {})
                r['member'] = handle

                hack = row['successfulHackCount']
                unhack = row['unsuccessfulHackCount']

                upsolve = \
                    row['party']['participantType'] == 'PRACTICE' or \
                    row['party']['participantType'] == 'VIRTUAL' and 'place' in r

                problems = r.setdefault('problems', {})
                for i, s in enumerate(row['problemResults']):
                    k = result_problems[i]['index']
                    points = float(s['points'])

                    n = s.get('rejectedAttemptCount')
                    if n is not None and contest_type == 'ICPC' and points + n > 0:
                        points = f'+{"" if n == 0 else n}' if points > 0 else f'-{n}'

                    if s['type'] == 'FINAL' and points:
                        p = {'result': points}
                        if 'bestSubmissionTimeSeconds' in s:
                            time = s['bestSubmissionTimeSeconds'] / 60
                            p['time'] = '%02d:%02d' % (time / 60, time % 60)
                        a = problems.setdefault(k, {})
                        if upsolve:
                            a['upsolving'] = p
                        else:
                            a.update(p)

                if row['rank'] and not upsolve:
                    r['place'] = row['rank']
                    r['penalty'] = row['penalty']
                    r['solving'] = row['points']
                    if contest_type == 'ICPC':
                        r['solving'] = int(round(r['solving']))

                if hack or unhack:
                    r['hack'] = {
                        'successful': hack,
                        'unsuccessful': unhack,
                    }

        def to_score(x):
            return (1 if x == '+' or float(x) > 0 else 0) if isinstance(x, str) else x

        def to_solve(x):
            return to_score(x) > 0

        for r in result.values():
            upsolving = 0
            solving = 0
            upsolving_score = 0
            for a in r['problems'].values():
                if 'upsolving' in a and to_solve(a['upsolving']['result']) > to_solve(a.get('result', 0)):
                    upsolving_score += to_score(a['upsolving']['result'])
                    upsolving += to_solve(a['upsolving']['result'])
                else:
                    solving += to_solve(a.get('result', 0))
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
            'problems': problems_info,
        }
        return standings


if __name__ == '__main__':
    pprint(Statistic(url='https://codeforces.com/contest/1164/', key='1164').get_result('abisheka'))
    pprint(Statistic(url='https://codeforces.com/contest/1202', key='1202').get_result('kmjp'))
    pprint(Statistic(url='https://codeforces.com/contest/1198', key='1198').get_result('yosupo'))
    pprint(Statistic(url='https://codeforces.com/contest/1198', key='1198').get_result('tourist'))
    pprint(Statistic(url='https://codeforces.com/contest/1160/', key='1160').get_result('Rafbill'))
    pprint(Statistic(url='https://codeforces.com/contest/1/', key='1').get_result('spartac'))
