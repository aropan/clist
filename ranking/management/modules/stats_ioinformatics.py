#!/usr/bin/env python

import re
from collections import OrderedDict
from pprint import pprint

from first import first

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if '//stats.ioinformatics.org/olympiads/' not in self.url:
            raise InitModuleException(f'Url {self.url} should be contains stats.ioinformatics.org/olympiads')

    def get_standings(self, users=None, statistics=None):
        result = {}
        problems_info = OrderedDict()
        year = self.start_time.year

        if not self.standings_url:
            self.standings_url = self.url.replace('/olympiads/', '/results/')

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table, as_list=True)

        idx = 0
        for r in table:
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            problem_idx = 0
            for k, v in r:
                if 'taskscore' in v.header.attrs.get('class', '').split():
                    problem_idx += 1
                    d = problems_info.setdefault(problem_idx, {})
                    d['short'] = str(problem_idx)
                    d['full_score'] = 100
                    d['name'] = k
                    try:
                        score = float(v.value)
                        p = problems.setdefault(str(problem_idx), {})
                        p['result'] = v.value
                        p['partial'] = score < 100
                    except Exception:
                        pass
                elif k == 'Abs.':
                    row['solving'] = float(v.value)
                elif k == 'Rank':
                    row['place'] = v.value.strip('*').strip('.')
                elif k == 'Contestant':
                    if not v.value:
                        idx += 1
                        member = f'{year}-{idx:06d}'
                        row['member'] = member
                    else:
                        url = first(v.column.node.xpath('a[@href]/@href'))
                        member = url.strip('/').split('/')[-1]
                        row['member'] = member
                        row['name'] = v.value
                elif k == 'Country':
                    country = re.sub(r'\s*[0-9]+$', '', v.value)
                    if country:
                        row['country'] = country
                else:
                    val = v.value.strip()
                    if k == 'Medal':
                        val = val.lower()
                    if val:
                        row[k] = val
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(url='http://stats.ioinformatics.org/olympiads/2008', standings_url=None)
    pprint(statictic.get_result('804'))
