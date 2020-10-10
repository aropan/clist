#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
from pprint import pprint

from ranking.management.modules.common import REQ, DOT
from ranking.management.modules.common import BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None, statistics=None):
        year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
        season = f'{year}-{year + 1}'

        result = {}

        page = REQ.get(self.standings_url)
        table = parsed_table.ParsedTable(html=page, xpath="//table[@class='ir-contest-standings']//tr")
        problems_info = collections.OrderedDict()
        for r in table:
            row = collections.OrderedDict()
            problems = row.setdefault('problems', {})
            ioi_total_fields = ['Sum', 'Сумма']
            ioi_style = any((f in r for f in ioi_total_fields))
            for k, v in list(r.items()):
                classes = v.attrs['class'].split()
                if 'ir-column-contestant' in classes:
                    row['member'] = v.value + ' ' + season
                    row['name'] = v.value
                elif 'ir-column-place' in classes:
                    row['place'] = v.value
                elif 'ir-column-penalty' in classes:
                    row['penalty'] = int(v.value)
                elif 'ir-problem-count' in classes or k in ioi_total_fields:
                    row['solving'] = int(v.value)
                elif len(k.split()[0]) == 1:
                    letter = k.split()[0]
                    problems_info[letter] = {'short': letter}
                    if v.value == DOT:
                        continue
                    p = problems.setdefault(letter, {})
                    values = v.value.replace('−', '-').split(' ')
                    p['result'] = values[0]
                    if len(values) > 1:
                        p['time'] = values[1]
                    if ioi_style and p['result'].isdigit():
                        val = int(p['result'])
                        if val:
                            p['partial'] = val < 100
                else:
                    row[k.lower()] = v.value
            if not problems or users and row['member'] not in users:
                continue
            member = row['member']
            if member in result:
                idx = 0
                while member + f'-{idx}' in result:
                    idx += 1
                member += f'-{idx}'
                row['member'] = member
            result[member] = row
        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='Олимпиада «Абитуриент ФПМИ» по направлению «Программирование» 2020',
        standings_url='https://acm.bsu.by/contests/106/standings/',
        key='2019-2020 Олимпиада Абитуриент ФПМИ',
    )
    pprint(statictic.get_result('Владислав Олешко 2019-2020'))
    statictic = Statistic(
        name='42',
        standings_url='https://acm.bsu.by/contests/40/standings/wide/',
        key='2017-2018 Олимпиада БГУ',
    )
    pprint(statictic.get_result('BelarusianSUIR #2 (Волчек, Соболь, Вистяж) 2017-2018'))
