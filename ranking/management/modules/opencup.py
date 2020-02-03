#!/usr/bin/env python

import re
import urllib.parse
from pprint import pprint
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url')

    def get_standings(self, users=None):
        if not hasattr(self, 'season'):
            if not hasattr(self, 'start_time'):
                self.season = self.key.split()[0]
            else:
                year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
                self.season = f'{year}-{year + 1}'

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
                    if k >= 'X':
                        continue
                    d = problems_info.setdefault(k, {})
                    d['short'] = k
                    if v.attrs.get('title'):
                        d['name'] = v.attrs['title']
                    if k.isdigit() and k in stages:
                        d['url'] = stages[k]
                    if ' ' in v.value:
                        p = problems.setdefault(k, {})
                        point, time = v.value.split()
                        if point == 'X':
                            p['binary'] = True
                            point = '+'
                        elif point == '0':
                            p['binary'] = False
                            point = '-1'
                        if 'opener' in v.attrs.get('class', '').split():
                            p['first_ac'] = True
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
                    row['solving'] = float(v.value)
                elif k == 'Time':
                    if "'" in v.value and '"' in v.value:
                        minute, seconds = map(int, re.findall('-?[0-9]+', v.value))
                        if minute < 0:
                            seconds = -seconds
                        row['penalty'] = f'{minute + seconds / 60:.2f}'
                    else:
                        row['penalty'] = int(v.value)
                elif k == 'Place':
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    row['member'] = v.value if ' ' not in v.value else v.value + ' ' + self.season
                    row['name'] = v.value
                else:
                    row[key] = v.value
            if 'solving' not in row:
                row['solving'] = row.pop('Rating', 0)
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        url='http://moscow2019.workshops.it-edu.mipt.ru/',
        standings_url='http://moscow2019.workshops.it-edu.mipt.ru/index.cgi?data=macros/amresults&menu=index&head=index&round=22&sbname=mipt2019n&class=mipt2019n&rid=1',  # noqa
        key='2019-2020 bla bla',
    )
    pprint(statictic.get_standings()['result']['SCH_Kazan+ITMO: Koresha (Gainullin, Rakhmatullin) 2019-2020'])
