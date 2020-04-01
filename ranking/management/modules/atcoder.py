# -*- coding: utf-8 -*-

import collections
import json
import re
from urllib.parse import urlparse
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack

import tqdm

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules import conf


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'
    RESULTS_URL_ = '{0.url}/results'
    HISTORY_URL_ = '{0.scheme}://{0.netloc}/users/{1}/history'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = self.key
        self._username = conf.ATCODER_HANDLE
        self._password = conf.ATCODER_PASSWORD

    def get_standings(self, users=None, statistics=None):
        url = f'{self.RESULTS_URL_.format(self)}/'
        page = REQ.get(url)
        form = REQ.form(limit=2, selectors=['class="form-horizontal"'])
        if form:
            form['post'].update({
                'username': self._username,
                'password': self._password,
            })
            page = REQ.get(form['url'], post=form['post'])

        match = re.search(r'var\s*results\s*=\s*(\[[^\n]*\]);$', page, re.MULTILINE)
        data = json.loads(match.group(1))
        results = {}
        for row in data:
            if not row.get('IsRated'):
                continue
            handle = row.pop('UserScreenName')
            r = collections.OrderedDict()
            for k in ['OldRating', 'NewRating', 'Performance']:
                if k in row:
                    r[k] = row[k]
            results[handle] = r

        url = f'{self.STANDING_URL_.format(self)}/json'
        page = REQ.get(url)
        data = json.loads(page)

        task_info = collections.OrderedDict()
        for t in data['TaskInfo']:
            k = t['TaskScreenName']
            task_info[k] = {
                'short': t['Assignment'],
                'name': t['TaskName'],
            }

        rows = data['StandingsData']

        handles_to_get_new_rating = []
        result = {}
        for row in rows:
            if not row['TaskResults']:
                continue
            handle = row.pop('UserScreenName')
            r = result.setdefault(handle, collections.OrderedDict())
            r['member'] = handle
            r['place'] = row.pop('Rank')
            total_result = row.pop('TotalResult')
            r['penalty'] = total_result['Elapsed'] // 10**9
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
            row.pop('UserIsDeleted', None)
            row.pop('Additional')
            rating = row.pop('Rating', None)
            if rating is not None:
                r['info'] = {'rating': rating}
            old_rating = row.pop('OldRating', None)
            r.update(row)

            if old_rating is not None:
                r['OldRating'] = old_rating

            if handle in results:
                r.update(results.pop(handle))

            if row['IsRated'] and 'NewRating' not in r:
                if statistics is None or 'new_rating' not in statistics.get(handle, {}):
                    handles_to_get_new_rating.append(handle)
                else:
                    r['OldRating'] = statistics[handle]['old_rating']
                    r['NewRating'] = statistics[handle]['new_rating']

        with ExitStack() as stack:
            executor = stack.enter_context(PoolExecutor(max_workers=8))
            pbar = stack.enter_context(tqdm.tqdm(total=len(handles_to_get_new_rating), desc='getting new rankings'))

            def fetch_data(handle):
                url = f'{self.HISTORY_URL_.format(urlparse(self.url), handle)}/json'
                data = json.loads(REQ.get(url))
                return handle, data

            for handle, data in executor.map(fetch_data, handles_to_get_new_rating):
                contest_addition_update = {}
                for contest in data:
                    if not contest.get('IsRated', True):
                        continue
                    key = contest['ContestScreenName'].split('.')[0]
                    if key == self.key:
                        result[handle]['OldRating'] = contest['OldRating']
                        result[handle]['NewRating'] = contest['NewRating']
                    else:
                        contest_addition_update[key] = collections.OrderedDict((
                            ('old_rating', contest['OldRating']),
                            ('new_rating', contest['NewRating']),
                        ))
                result[handle]['contest_addition_update'] = contest_addition_update
                pbar.update()

        standings = {
            'result': result,
            'url': self.STANDING_URL_.format(self),
            'problems': list(task_info.values()),
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://atcoder.jp/contests/abc150', key='abc150')
    pprint(statistic.get_result('Geothermal'))
    statistic = Statistic(url='https://atcoder.jp/contests/agc031', key='agc031')
    pprint(statistic.get_result('tourist'))
