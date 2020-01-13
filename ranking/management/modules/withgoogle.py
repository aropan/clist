#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import re
import json
import urllib.parse
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime

import tqdm

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://codejam.googleapis.com/scoreboard/{id}/poll?p='

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def _api_get_standings(self, users=None):
        match = re.search('/([0-9a-f]{16})$', self.url)
        if not match:
            raise ExceptionParseStandings(f'Not found id in url = {self.url}')
        self.id = match.group(1)
        standings_url = self.url

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)

        def get(offset, num):
            query = f'{{"min_rank":{offset},"num_consecutive_users":{num}}}'
            base64_query = base64.b64encode(query.encode())
            url = api_ranking_url_format + base64_query.decode()
            content = REQ.get(url)
            content = content.replace('-', '+')
            content = content.replace('_', '/')
            content = re.sub(r'[^A-Za-z0-9\+\/]', '', content)
            content += '=' * ((4 - len(content) % 4) % 4)
            data = json.loads(base64.b64decode(content).decode())
            return data

        data = get(1, 1)
        problems_info = OrderedDict([
            (
                task['id'],
                {
                    'code': task['id'],
                    'name': task['title'],
                    'full_score': sum([test['value'] for test in task['tests']])
                }
            )
            for task in data['challenge']['tasks']
        ])

        num_consecutive_users = 200
        n_page = (data['full_scoreboard_size'] - 1) // num_consecutive_users + 1

        def fetch_page(page):
            return get(page * num_consecutive_users + 1, num_consecutive_users)

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in tqdm.tqdm(executor.map(fetch_page, range(n_page)), total=n_page):
                for row in data['user_scores']:
                    if not row['task_info']:
                        continue
                    handle = row.pop('displayname')

                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['place'] = row.pop('rank')
                    r['solving'] = row.pop('score_1')
                    r['penalty'] = self.to_time(-row.pop('score_2') / 10**6)

                    country = row.pop('country', None)
                    if country:
                        r['country'] = country

                    solved = 0
                    problems = r.setdefault('problems', {})
                    for task_info in row['task_info']:
                        tid = task_info['task_id']
                        p = problems.setdefault(tid, {})
                        p['time'] = self.to_time(task_info['penalty_micros'] / 10**6)
                        p['result'] = task_info['score']
                        if p['result'] and p['result'] != problems_info[tid]['full_score']:
                            p['partial'] = True
                        if task_info['penalty_attempts']:
                            p['penalty'] = task_info['penalty_attempts']
                        solved += task_info['tests_definitely_solved']
                    r['solved'] = {'solving': solved}

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }
        return standings

    def _old_get_standings(self, users=None):
        if not self.standings_url:
            self.standings_url = self.url.replace('/dashboard', '/scoreboard')

        result = {}

        page = REQ.get(self.standings_url)

        matches = re.finditer(r'GCJ.(?P<key>[^\s]*)\s*=\s*"?(?P<value>[^";]*)', page)
        vs = {m.group('key'): m.group('value') for m in matches}
        vs['rowsPerPage'] = int(vs['rowsPerPage'])

        matches = re.finditer(r'GCJ.problems.push\((?P<problem>{[^}]*})', page)
        problems_info = OrderedDict([])
        problems = [json.loads(m.group('problem')) for m in matches]

        matches = re.finditer(r'(?P<new>\(\);)?\s*io.push\((?P<subtask>{[^}]*})', page)
        tid = -1
        for idx, m in enumerate(matches):
            subtask = json.loads(m.group('subtask'))
            if m.group('new'):
                tid += 1
            idx = str(idx)
            task = problems[tid].copy()
            task.update(subtask)
            task['name'] = task.pop('title')
            task['code'] = idx
            task['full_score'] = task.pop('points')
            problems_info[idx] = task

        def fetch_page(page_idx):
            nonlocal vs
            params = {
                'cmd': 'GetScoreboard',
                'contest_id': vs['contestId'],
                'show_type': 'all',
                'start_pos': page_idx * vs['rowsPerPage'] + 1,
                'csrfmiddlewaretoken': vs['csrfMiddlewareToken'],
            }
            url = os.path.join(self.standings_url, 'do') + '?' + urllib.parse.urlencode(params)
            page = REQ.get(url)
            data = json.loads(page)
            return data

        data = fetch_page(0)
        n_page = (data['stat']['nrp'] - 1) // vs['rowsPerPage'] + 1

        def time2str(t):
            h = t // 3600
            if h:
                return f'{h}:{t // 60 % 60:02d}:{t % 60:02d}'
            return f'{t // 60}:{t % 60:02d}'

        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in tqdm.tqdm(executor.map(fetch_page, range(n_page)), total=n_page):
                for row in data['rows']:
                    handle = row.pop('n')
                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['country'] = row.pop('c')
                    r['penalty'] = time2str(row.pop('pen'))
                    r['solving'] = row.pop('pts')
                    r['place'] = row.pop('r')

                    problems = r.setdefault('problems', {})
                    solved = 0
                    for idx, (attempt, time) in enumerate(zip(row.pop('att'), row.pop('ss'))):
                        if attempt:
                            p = problems.setdefault(str(idx), {})
                            if time == -1:
                                p['result'] = -attempt
                            else:
                                solved += 1
                                p['result'] = '+' if attempt == 1 else f'+{attempt - 1}'
                                p['time'] = time2str(time)
                    r['solved'] = {'solving': solved}

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings

    def get_standings(self, users=None):
        if '/codingcompetitions.withgoogle.com/' in self.url:
            return self._api_get_standings(users)
        if '/code.google.com/' in self.url or '/codejam.withgoogle.com/' in self.url:
            return self._old_get_standings(users)
        raise InitModuleException(f'url = {self.url}')


if __name__ == "__main__":
    from pprint import pprint
    statistics = [
        Statistic(
            name='Kick Start. Round H',
            url='https://codejam.withgoogle.com/codejam/contest/3324486/dashboard',
            key='3324486',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Code Jam. AMER Semifinal',
            url='https://code.google.com/codejam/contest/32008/dashboard',
            key='32008',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Code Jam. Round 1A',
            url='https://code.google.com/codejam/contest/32016/dashboard',
            key='32016',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Round 2 2019',
            url='https://codingcompetitions.withgoogle.com/codejam/round/0000000000051679',
            key='0d4dvct96b7cpf0tml4elq0n9r',
            start_time=datetime.now(),
            standings_url=None,
        ),
        Statistic(
            name='Round B 2019',
            url='https://codingcompetitions.withgoogle.com/kickstart/round/0000000000050eda',
            key='0d4dvct96b7cpf0tml4elq0n9r',
            start_time=datetime.now(),
            standings_url=None,
        ),
    ]
    for statictic in statistics:
        standings = statictic.get_standings()
        result = standings.pop('result', None)
        if result:
            scores = [float(r['solving']) for r in result.values()]
            scores.sort()
            score = scores[len(scores) * 9 // 10]
            result = [r for r in result.values() if float(r['solving']) == score]
            from random import choice
            pprint(choice(result))
        pprint(standings)
