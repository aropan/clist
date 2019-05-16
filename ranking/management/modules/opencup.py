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
                if len(k) == 1:
                    if ' ' in v.value:
                        p = problems.setdefault(k, {})
                        p['name'] = v.attrs['title']
                        point, time = v.value.split()
                        p['time'] = time
                        p['result'] = point
                elif k == 'Total':
                    row['solving'] = int(v.value)
                elif k == 'Time':
                    row['penalty'] = int(v.value)
                elif k == 'Place':
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
        name='42',
        standings_url='http://opentrains.snarknews.info/~ejudge/res/res10391',
        key='2017-2018 Grand Prix of Romania',
    )
    pprint(statictic.get_result('spb27 : Sayranov 2017-2018'))
    statictic = Statistic(
        name='42',
        standings_url='http://opentrains.snarknews.info/~ejudge/res/res10435',
        key='2018-2019 Grand Prix of Korea',
    )
    pprint(statictic.get_result('Belarusian SUIR #3 anti_bsuir_1 : Vishneuski, Shavel, Udovin 2018-2019'))
