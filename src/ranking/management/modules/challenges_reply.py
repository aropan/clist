#!/usr/bin/env python

import json
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytz

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        season = self.get_season()
        domain = urlparse(self.url).netloc

        def get(url, *args, **kwargs):
            cache = kwargs.pop('cache', False)
            if cache and self.start_time + timedelta(days=30) < pytz.UTC.localize(datetime.utcnow()):
                url += '&params.fromCache=true'

            page = REQ.get(url, *args, **kwargs)
            for c in REQ.get_raw_cookies():
                if c.domain == domain and c.name.startswith('__'):
                    c.value = re.sub(r'\s*', '', c.value)
            return page

        REQ.last_url = self.url

        page = get('/tamtamy/home.action')
        if not re.search('<a[^>]*href="[^"]*logout[^"]*"[^>]*>', page, re.I):
            get('/tamtamy/user/signIn.action', post={
                'username': conf.CHALLENGES_REPLY_EMAIL,
                'password': conf.CHALLENGES_REPLY_PASSWORD,
                'remember': True,
                'pageSourceType': 'MODAL',
            })

        result = {}
        problems_info = OrderedDict()

        def to_time(value):
            return self.to_time(value / 1000 - self.start_time.timestamp(), num=3)

        offset = 0
        max_solving = 0
        problems_max_score = {}
        has_delta = False
        has_members = False
        while offset is not None:
            url = ("/tamtamy/api/challenge-leaderboard-entry.json"
                   f"?params.challengeId={self.key}&params.firstResult={offset}&params.numberOfResult=100")
            try:
                data = get(url, cache=True)
                if isinstance(data, str):
                    data = json.loads(data)
            except FailOnGetResponse as e:
                raise ExceptionParseStandings(str(e))

            for k in 'error', 'errorMessage':
                if data.get(k):
                    raise ExceptionParseStandings(data[k])

            offset = data['paginationInfo']['nextOffset']
            for r in data['list']:
                row = {}
                name = r['competitorName']
                name = re.sub('[\r\n]', '', name)
                row['member'] = f'{name} {season}'
                row['name'] = name
                row['solving'] = r['score']
                row['country'] = r['competitorFlagKey']
                row['place'] = r['position']
                row['delta'] = int(r['delta'])
                has_delta |= bool(row['delta'])

                if r.get('penalty'):
                    row['penalty'] = self.to_time(r['penalty'], num=3)
                elif r.get('bestScoreReached'):
                    row['total_time'] = to_time(r['bestScoreReached']['time'])

                members = set()
                problems = row.setdefault('problems', {})
                if r.get('maxScoring'):
                    for scoring in r['maxScoring']:
                        k = scoring['input']['fileName'].split('.')[0]
                        if k not in problems_info:
                            problems_info[k] = {'short': k}
                        if not scoring['outputFn']:
                            continue

                        p = problems.setdefault(k, {})
                        if scoring['status'] == "VALID":
                            p['result'] = scoring['score']
                            problems_max_score[k] = max(problems_max_score.get(k, 0), p['result'])
                        else:
                            p['binary'] = False
                        member = scoring['author']['nickname'] or scoring['author']['fullName']
                        p['author'] = member
                        members.add(member)
                if r.get('problemStatus'):
                    for status in r['problemStatus']:
                        k = status['name']
                        if k not in problems_info:
                            problems_info[k] = {'name': k}
                        if not status.get('levelStatus'):
                            continue

                        time = 0
                        score = 0
                        for level in status['levelStatus']:
                            if level['points']:
                                time += level['penalty'] / 1000
                                score += level['points']

                        problems[k] = {
                            'result': score,
                            'time': self.to_time(time, num=3),
                        }
                if r.get('categoryScores'):
                    for category in r['categoryScores']:
                        k = category['categoryName']
                        if k not in problems_info:
                            problems_info[k] = {'name': k}
                        if not category.get('score'):
                            continue

                        p = problems.setdefault(k, {})
                        p['result'] = category['score']
                        p['partial'] = category['solvedCount'] < category['subchallengesCount']

                if not row['solving'] and 'penalty' not in row and 'time' not in row and not problems:
                    offset = None
                    break

                if r.get('maxScoring') or not result:
                    max_solving = max(max_solving, row['solving'])

                if members:
                    row['_members'] = [{'name': member} for member in members]
                    has_members = True

                result[row['member']] = row

        if has_delta:
            for row in result.values():
                if row['place'] + row['delta'] > len(result):
                    row.pop('delta')
        elif statistics:
            for member, row in result.items():
                delta = statistics.get(member, {}).get('delta')
                if delta is not None:
                    row['delta'] = delta

        if problems_max_score:
            max_solving = 0
            for k, v in problems_max_score.items():
                problems_info[k]['max_score'] = v
                max_solving += v
            for row in result.values():
                for k, p in row.get('problems', {}).items():
                    if 'result' in p:
                        p['status'] = f"{(problems_max_score[k] - p['result']) * 100 / max_solving :.2f}%"
                        if problems_max_score[k] - p['result'] < 1e-9:
                            p['max_score'] = True

        if max_solving:
            for row in result.values():
                row['percent'] = f"{row['solving'] * 100 / max_solving:.2f}%"

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
            'fields_types': {'delta': ['delta']},
        }
        if has_members:
            options = standings.setdefault('options', {})
            options.update({'members_message': 'members who submitted'})

        return standings
