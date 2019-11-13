#!/usr/bin/env python

import re
import urllib.parse
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
        if not hasattr(self, 'season'):
            self.season = self.key.split()[0]

        result = {}
        problems_info = OrderedDict()

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)

        matches = re.finditer(
            r'''
            <a[^>]*>[^<]*Day\s*(?P<day>[0-9]+):[^<]*<[^#]*?
            <a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*(?:Div\s*[A1]\s*)?Results\s*</a>
            ''',
            page,
            re.IGNORECASE | re.VERBOSE,
        )
        stages = {m.group('day'): urllib.parse.urljoin(self.standings_url, m.group('url')) for m in matches}

        for r in table:
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            for key, v in list(r.items()):
                if re.match('^Stage [0-9]+$', key):
                    k = key.split()[1]
                else:
                    k = key.split()[0]
                if len(k) == 1 and 'A' <= k <= 'Z' or k.isdigit():
                    d = problems_info.setdefault(k, {})
                    d['short'] = k
                    if v.attrs.get('title'):
                        d['name'] = v.attrs['title']
                    if k.isdigit() and k in stages:
                        d['url'] = stages[k]
                    if ' ' in v.value:
                        p = problems.setdefault(k, {})
                        point, time = v.value.split()
                        p['time'] = time
                        p['result'] = point
                    else:
                        try:
                            point = float(v.value)
                            p = problems.setdefault(k, {})
                            p['result'] = point
                        except Exception:
                            pass
                elif k == 'Total':
                    row['solving'] = int(v.value)
                elif k == 'Rating':
                    row['solving'] = float(v.value)
                elif k == 'Time':
                    if "'" in v.value and '"' in v.value:
                        minute, seconds = map(int, re.findall('[0-9]+', v.value))
                        row['penalty'] = f'{minute + seconds / 60:.2f}'
                    else:
                        row['penalty'] = int(v.value)
                elif k == 'Place':
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    row['member'] = v.value + ' ' + self.season
                    row['name'] = v.value
                else:
                    row[key] = v.value
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    # statictic = Statistic(
    #     name='42',
    #     url='http://official.contest.yandex.ru/opencupXIX/contest/9552/enter?data=ocj%2Fschedule&menu=index&head=index',
    #     standings_url='http://opencup.ru/index.cgi?data=macros%2Fstage&menu=index&head=index&stg=13&region=main&ncup=ocj&class=ocj',  # noqa
    #     key='2018-2019 Grand Prix of Bytedance',
    # )
    # pprint(statictic.get_standings()['problems'])
    statictic = Statistic(
        name='42',
        url='http://moscow2019.workshops.it-edu.mipt.ru/',
        standings_url='http://moscow2019.workshops.it-edu.mipt.ru/index.cgi?data=macros/amresults&menu=index&head=index&round=22&sbname=mipt2019n&class=mipt2019n&rid=1',  # noqa
        key='2019-2020 bla bla',
    )
    pprint(statictic.get_standings()['result']['SCH_Kazan+ITMO: Koresha (Gainullin, Rakhmatullin) 2019-2020'])
