#!/usr/bin/env python

import re
from pprint import pprint
from collections import OrderedDict
from datetime import timedelta

from first import first

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules import conf


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            self.standings_url = f'https://projecteuler.net/fastest={self.key}'

        result = {}

        page = REQ.get(self.standings_url, headers=conf.PROJECTEULER_COOKIE_HEADER)
        regex = '<table[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)

        for r in table:
            row = OrderedDict()
            row['solving'] = 1
            for k, v in r.items():
                if isinstance(v, list):
                    place, country = v
                    row['place'] = re.match('[0-9]+', place.value).group(0)
                    country = first(country.column.node.xpath('.//@title'))
                    if country:
                        row['country'] = country
                elif k == 'Time To Solve':
                    params = {}
                    for x in v.value.split(', '):
                        value, field = x.split()
                        if field[-1] != 's':
                            field += 's'
                        params[field] = int(value)
                    delta = timedelta(**params)
                    row['penalty'] = f'{delta.total_seconds() / 60:.2f}'
                elif k == 'User':
                    member = first(v.column.node.xpath('.//@title')) or v.value
                    row['member'] = member
                else:
                    row[k.lower()] = v.value
            if 'member' not in row:
                continue
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': [],
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(url='https://projecteuler.net/problem=689', key='689', standings_url=None)
    pprint(statictic.get_result('theshuffler', 'Tepsi', 'jpeg13'))
