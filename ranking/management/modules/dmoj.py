#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import time
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://dmoj.ca/api/contest/info/{key}'
    PROBLEM_URL_ = 'https://dmoj.ca/problem/{short}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):

        url = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        try:
            time.sleep(1)
            page = REQ.get(url)
        except Exception as e:
            return {'action': 'delete'} if e.args[0].code == 404 else {}

        data = json.loads(page)

        problems_info = []
        for p in data['problems']:
            info = {
                'short': p['code'],
                'name': p['name'],
            }
            info['url'] = self.PROBLEM_URL_.format(**info)
            if p.get('points'):
                info['full_score'] = p['points']
            problems_info.append(info)

        result = {}
        prev = None
        rankings = sorted(data['rankings'], key=lambda x: (-x['points'], x['cumtime']))
        for index, r in enumerate(rankings, start=1):
            solutions = r.pop('solutions')
            if not any(solutions):
                continue
            handle = r.pop('user')
            row = result.setdefault(handle, {})

            row['member'] = handle
            row['solving'] = r.pop('points')
            cumtime = r.pop('cumtime')
            if cumtime:
                row['penalty'] = self.to_time(cumtime)

            curr = (row['solving'], cumtime)
            if curr != prev:
                prev = curr
                rank = index
            row['place'] = rank

            solved = 0
            problems = row.setdefault('problems', {})
            for prob, sol in zip(data['problems'], solutions):
                if not sol:
                    continue
                p = problems.setdefault(prob['code'], {})
                if sol['points'] > 0 and prob.get('partial'):
                    p['partial'] = prob['points'] - sol['points'] > 1e-7
                    if not p['partial']:
                        solved += 1
                p['result'] = sol.pop('points')
                t = sol.pop('time')
                if t:
                    p['time'] = self.to_time(t)

            r.pop('is_disqualified', None)
            row.update({k: v for k, v in r.items() if k not in row})

            row['solved'] = {'solving': solved}

        standings_url = hasattr(self, 'standings_url') and self.standings_url or self.url.rstrip('/') + '/ranking/'
        standings = {
            'result': result,
            'url': standings_url,
            'problems': problems_info,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='42',
        url='https://dmoj.ca/contest/dmopc18c2/',
        key='dmopc18c2',
    )
    pprint(statictic.get_result('ayyyyyyyyyyyyyLMAO'))

    statictic = Statistic(
        name="Mock CCO '19 Contest 2, Day 1",
        url='http://www.dmoj.ca/contest/mcco19c2d1',
        key='mcco19c2d1',
    )
    pprint(statictic.get_result('GSmerch', 'georgehtliu'))

    statictic = Statistic(
        name='Deadly Serious Contest Day 1',
        url='http://www.dmoj.ca/contest/dsc19d1',
        key='dsc19d1',
    )
    pprint(statictic.get_result('scanhex', 'wleung_bvg'))

    statictic = Statistic(
        name="Mock CCO '19 Contest 2, Day 1",
        url='https://dmoj.ca/contest/tle16',
        key='tle16',
    )
    pprint(statictic.get_standings())
