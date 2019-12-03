#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
from datetime import datetime
from pprint import pprint
from collections import OrderedDict

from common import REQ, DOT, SPACE, BaseModule, parsed_table


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        if not self.standings_url:
            return {}

        page = REQ.get(self.standings_url)

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)
        mapping_key = {
            'rank': 'place',
            'rankl': 'place',
            'party': 'name',
            'solved': 'solving',
        }
        result = {}
        problems_info = OrderedDict()
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                c = v.attrs['class'].split()[0]
                if c in ['problem', 'ioiprob']:
                    problems_info[k] = {'short': k, 'name': v.attrs['title']}
                    if v.value != DOT:
                        p = problems.setdefault(k, {})

                        first_ac = v.column.node.xpath('.//*[@class="first-to-solve"]')
                        if len(first_ac):
                            p['first_ac'] = True

                        v = v.value
                        if SPACE in v:
                            v, t = v.split(SPACE, 1)
                            p['time'] = t
                        p['result'] = v
                else:
                    c = mapping_key.get(c, c)
                    row[c] = v.value
            if 'penalty' not in row:
                row['name'] = re.sub(r'\s*\([^\)]*\)\s*$', '', row['name'])
                solved = [p for p in list(problems.values()) if p['result'] == '100']
                row['solved'] = {'solving': len(solved)}
            elif re.match('^[0-9]+$', row['penalty']):
                row['penalty'] = int(row['penalty'])

            for f in 'diploma', 'medal':
                medal = row.pop(f, None) or row.pop(f.title(), None)
                if medal:
                    if medal in ['З', 'G']:
                        row['medal'] = 'gold'
                    elif medal in ['С', 'S']:
                        row['medal'] = 'silver'
                    elif medal in ['Б', 'B']:
                        row['medal'] = 'bronze'
                    break
            row['member'] = row['name'] + ' ' + season
            result[row['member']] = row
        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        standings_url='http://neerc.ifmo.ru/school/io/archive/20190324/standings-20190324-individual.html',
        start_time=datetime.strptime('20190324', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        standings_url='http://neerc.ifmo.ru/school/io/archive/20080510/standings-20080510-advanced.html',
        start_time=datetime.strptime('20080510', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        standings_url='https://nerc.itmo.ru/school/archive/2019-2020/ru-olymp-team-russia-2019-standings.html',
        start_time=datetime.strptime('20191201', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
