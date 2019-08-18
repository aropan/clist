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
        season = self.key.split()[0]

        result = {}
        problems_info = OrderedDict()

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
                    d = {'short': k}
                    if v.attrs['title']:
                        d['name'] = v.attrs['title']
                    problems_info[k] = d
                    if ' ' in v.value:
                        p = problems.setdefault(k, {})
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
    statictic = Statistic(
        name='42',
        url='http://official.contest.yandex.ru/opencupXIX/contest/9552/enter?data=ocj%2Fschedule&menu=index&head=index',
        standings_url='http://opencup.ru/index.cgi?data=macros%2Fstage&menu=index&head=index&stg=13&region=main&ncup=ocj&class=ocj',  # noqa
        key='2018-2019 Grand Prix of Bytedance',
    )
    pprint(statictic.get_standings()['problems'])
