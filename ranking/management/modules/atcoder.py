# -*- coding: utf-8 -*-

from common import REQ, BaseModule

import json
from pprint import pprint


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = self.key

    def get_standings(self, users=None):

        url = f'{self.STANDING_URL_.format(self)}/json'
        page = REQ.get(url)

        data = json.loads(page)

        task_info = {}
        for t in data['TaskInfo']:
            k = t['TaskScreenName']
            task_info[k] = {
                'letter': t['Assignment'],
                'name': t['TaskName'],
            }

        rows = data['StandingsData']

        result = {}
        for row in rows:
            if not row['TaskResults']:
                continue
            handle = row['UserScreenName']
            r = result.setdefault(handle, {})
            r['member'] = handle
            r['place'] = row['Rank']
            r['penalty'] = row['TotalResult']['Elapsed'] // 10**9
            r['score'] = row['TotalResult']['Score'] / 100.
            r['solving'] = int(round(r['score']))

            problems = r.setdefault('problems', {})
            solving = 0
            for k, v in row['TaskResults'].items():
                if 'Score' not in v:
                    continue
                letter = task_info[k]['letter']
                p = problems.setdefault(letter, {})
                p['name'] = task_info[k]['name']

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

        standings = {
            'result': result,
            'url': self.STANDING_URL_.format(self),
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://atcoder.jp/contests/agc031', key='agc031')
    pprint(statistic.get_result('tourist'))
