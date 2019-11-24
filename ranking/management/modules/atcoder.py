# -*- coding: utf-8 -*-

import collections
import json
from pprint import pprint

from common import REQ, BaseModule


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = self.key

    def get_standings(self, users=None):

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

        result = {}
        for row in rows:
            if not row['TaskResults']:
                continue
            handle = row.pop('UserScreenName')
            r = result.setdefault(handle, {})
            r['member'] = handle
            r['place'] = row.pop('Rank')
            total_result = row.pop('TotalResult')
            r['penalty'] = total_result['Elapsed'] // 10**9
            r['solving'] = total_result['Score'] / 100.
            r['country'] = row.pop('Country')

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
            r.update(row)

        standings = {
            'result': result,
            'url': self.STANDING_URL_.format(self),
            'problems': list(task_info.values()),
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://atcoder.jp/contests/agc031', key='agc031')
    pprint(statistic.get_result('tourist'))
