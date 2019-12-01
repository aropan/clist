#!/usr/bin/env python

import re
from pprint import pprint
from collections import OrderedDict

from common import REQ, BaseModule, parsed_table
from excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        result = {}
        problems_info = OrderedDict()

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if not match:
            page = re.sub('<table[^>]*wrapper[^>]*>', '', page)
            regex = '<table[^>]*>.*?</table>'
            match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                k = k.split()[0]
                if k == 'Total' or k == '=':
                    row['solving'] = int(v.value)
                elif len(k) <= 3:
                    problems_info[k] = {'short': k}
                    if 'title' in v.attrs:
                        problems_info[k]['name'] = v.attrs['title']

                    if '-' in v.value or '+' in v.value or '?' in v.value:
                        p = problems.setdefault(k, {})
                        if ' ' in v.value:
                            point, time = v.value.split()
                            p['time'] = time
                        else:
                            point = v.value
                        p['result'] = point
                elif k == 'Time':
                    row['penalty'] = int(v.value)
                elif k.lower() in ['place', 'rank']:
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    row['member'] = v.value + ' ' + season
                    row['name'] = v.value
                else:
                    row[k] = v.value
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    from datetime import datetime
    statictic = Statistic(
        name='ICPC 2019-2020, NEERC - Northern Eurasia Finals',
        standings_url='http://neerc.ifmo.ru/archive/2019/standings.html',
        key='2019-2020 NEERC',
        start_time=datetime.strptime('2005-09-02', '%Y-%m-%d'),
    )
    pprint(statictic.get_standings())
