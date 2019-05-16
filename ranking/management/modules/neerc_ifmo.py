#!/usr/bin/env python

from common import REQ, BaseModule, parsed_table
from excepts import InitModuleException

import re
from pprint import pprint


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None):
        season = self.key.split()[0]

        result = {}

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                k = k.split()[0]
                if k == 'Total' or k == '=':
                    row['solving'] = int(v.value)
                elif len(k) == 1:
                    if '-' in v.value or '+' in v.value:
                        p = problems.setdefault(k, {})
                        p['name'] = v.attrs['title']
                        if ' ' in v.value:
                            point, time = v.value.split()
                            p['time'] = time
                        else:
                            point = v.value
                        p['result'] = point
                elif k == 'Time':
                    row['penalty'] = int(v.value)
                elif k == 'Place' or k == 'Rank':
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    row['member'] = v.value + ' ' + season
                else:
                    row[k] = v.value
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='ICPC 2018-2019, NEERC - Northern Eurasia Finals',
        standings_url='http://neerc.ifmo.ru/archive/2018/standings.html',
        key='2018-2019 NEERC',
    )
    pprint(statictic.get_result('Tbilisi Free U 5 (Emnadze, Kotoreishvili, Grdzelishvili) 2018-2019'))
