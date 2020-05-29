# -*- coding: utf-8 -*-

import collections
import json
import re
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules import conf


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'
    RESULTS_URL_ = '{0.url}/results'
    PROBLEM_URL_ = '{0.url}/tasks/{0.key}_{1}'
    HISTORY_URL_ = '{0.scheme}://{0.netloc}/users/{1}/history'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = self.key
        self._username = conf.ATCODER_HANDLE
        self._password = conf.ATCODER_PASSWORD

    def _get(self, *args, **kwargs):
        page = REQ.get(*args, **kwargs)
        form = REQ.form(limit=2, selectors=['class="form-horizontal"'])
        if form:
            form['post'].update({
                'username': self._username,
                'password': self._password,
            })
            page = REQ.get(form['url'], post=form['post'])
        return page

    def get_standings(self, users=None, statistics=None):
        page = self._get(self.url)
        match = re.search(r'(?<=<li>)Writer:.*', page)
        writers = []
        if match:
            matches = re.findall('(?<=>)[^<]+(?=<)', match.group())
            writers = list()
            for m in matches:
                writers.extend(map(str.strip, re.split(r',\s*', m)))
            writers = [w for w in writers if w and w != '?']

        url = f'{self.RESULTS_URL_.format(self)}/'
        page = self._get(url)

        match = re.search(r'var\s*results\s*=\s*(\[[^\n]*\]);$', page, re.MULTILINE)
        data = json.loads(match.group(1))
        results = {}
        for row in data:
            if not row.get('IsRated'):
                continue
            handle = row.pop('UserScreenName')
            if users and handle not in users:
                continue
            r = collections.OrderedDict()
            for k in ['OldRating', 'NewRating', 'Performance']:
                if k in row:
                    r[k] = row[k]
            results[handle] = r

        url = f'{self.STANDING_URL_.format(self)}/json'
        page = self._get(url)
        data = json.loads(page)

        task_info = collections.OrderedDict()
        for t in data['TaskInfo']:
            k = t['TaskScreenName']
            task_info[k] = {
                'short': t['Assignment'],
                'name': t['TaskName'],
                'url': self.PROBLEM_URL_.format(self, t['Assignment'].lower()),
            }

        rows = data['StandingsData']

        result = {}
        for row in rows:
            if not row['TaskResults']:
                continue
            handle = row.pop('UserScreenName')
            if users and handle not in users:
                continue
            r = result.setdefault(handle, collections.OrderedDict())
            r['member'] = handle
            if row.pop('UserIsDeleted', None):
                r['action'] = 'delete'
                continue
            r['place'] = row.pop('Rank')
            total_result = row.pop('TotalResult')

            penalty = total_result['Elapsed'] // 10**9
            r['penalty'] = f'{penalty // 60}:{penalty % 60:02d}'

            r['solving'] = total_result['Score'] / 100.
            r['country'] = row.pop('Country')
            if 'UserName' in row:
                r['name'] = row.pop('UserName')

            problems = r.setdefault('problems', {})
            solving = 0
            task_results = row.pop('TaskResults', {})
            for k, v in task_results.items():
                if 'Score' not in v:
                    continue
                letter = task_info[k]['short']
                p = problems.setdefault(letter, {})

                if v['Score'] > 0:
                    solving += 1

                    p['result'] = v['Score'] / 100.

                    seconds = v['Elapsed'] // 10**9
                    p['time'] = f'{seconds // 60}:{seconds % 60:02d}'

                    if v['Penalty'] > 0:
                        p['penalty'] = v['Penalty']
                else:
                    p['result'] = f"-{v['Failure']}"
            r['solved'] = {'solving': solving}

            row.update(r)
            row.pop('Additional')
            rating = row.pop('Rating', None)
            if rating is not None:
                r['info'] = {'rating': rating}
            old_rating = row.pop('OldRating', None)
            r.update(row)

            if handle in results:
                r.update(results.pop(handle))

            if old_rating is not None:
                r['OldRating'] = old_rating

        standings = {
            'result': result,
            'url': self.STANDING_URL_.format(self),
            'problems': list(task_info.values()),
            'writers': writers,
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://atcoder.jp/contests/abc150', key='abc150')
    pprint(statistic.get_result('Geothermal'))
    statistic = Statistic(url='https://atcoder.jp/contests/agc031', key='agc031')
    pprint(statistic.get_result('tourist'))
