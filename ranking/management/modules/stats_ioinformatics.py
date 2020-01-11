#!/usr/bin/env python

import re
from pprint import pprint
from collections import OrderedDict

from first import first

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.url.startswith('http://stats.ioinformatics.org/olympiads/'):
            raise InitModuleException(f'Url = {self.url} should be from stats.ioinformatics.org')

    def get_standings(self, users=None):
        result = {}
        problems_info = OrderedDict()

        if not self.standings_url:
            self.standings_url = self.url.replace('/olympiads/', '/results/')

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table, as_list=True)

        for r in table:
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            problem_idx = 0
            for k, v in r:
                if 'taskscore' in v.header.attrs.get('class', '').split():
                    problem_idx += 1
                    d = problems_info.setdefault(problem_idx, {})
                    d['short'] = str(problem_idx)
                    d['name'] = k
                    p = problems.setdefault(str(problem_idx), {})
                    p['result'] = v.value
                elif k == 'Abs.':
                    row['solving'] = float(v.value)
                elif k == 'Rank':
                    row['place'] = v.value.strip('*').strip('.')
                elif k == 'Contestant':
                    url = first(v.column.node.xpath('a[@href]/@href'))
                    member = url.strip('/').split('/')[-1]
                    row['member'] = member
                    row['name'] = v.value
                elif k == 'Country':
                    row['country'] = re.sub(r'\s*[0-9]+$', '', v.value)
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
    statictic = Statistic(url='http://stats.ioinformatics.org/olympiads/2008', standings_url=None)
    pprint(statictic.get_result('804'))
