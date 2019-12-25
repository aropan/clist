#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse
from pprint import pprint
from collections import OrderedDict

from common import REQ
from common import BaseModule
from common import parsed_table
from excepts import InitModuleException
from datetime import datetime


class Statistic(BaseModule):
    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            url = 'http://usaco.org/index.php?page=contests'
            page = REQ.get(url)
            matches = re.finditer('<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<name>[^<]*[0-9]{4}[^<]*Results)</a>', page)
            month = self.start_time.strftime('%B').lower()
            prev_standings_url = None
            for match in matches:
                name = match.group('name').lower()
                if (month in name or self.name.lower() in name) and str(self.start_time.year)in name:
                    self.standings_url = urllib.parse.urljoin(url, match.group('url'))
                    break
                if (month in name or self.name.lower() in name) and str(self.start_time.year - 1) in name:
                    prev_standings_url = urllib.parse.urljoin(url, match.group('url'))
            else:
                if prev_standings_url is not None:
                    pred_standings_url = re.sub('[0-9]+', lambda m: str(int(m.group(0)) + 1), prev_standings_url)
                    url = 'http://usaco.org/'
                    page = REQ.get(url)
                    matches = re.finditer('<a[^>]*href="?(?P<url>[^"]*)"?[^>]*>here</a>', page)
                    for match in matches:
                        standings_url = urllib.parse.urljoin(url, match.group('url'))
                        if standings_url == pred_standings_url:
                            self.standings_url = standings_url
                            break
                if not self.standings_url:
                    raise InitModuleException(f'Not found standings url with'
                                              f'month = {month}, '
                                              f'year = {self.start_time.year}, '
                                              f'name = {self.name}')

    def get_standings(self, users=None):
        page = REQ.get(self.standings_url)

        result = {}

        problems_info = OrderedDict()

        divisions = re.finditer('<a[^>]*href="(?P<url>[^"]*data[^"]*_(?P<name>[^_]*)_results.html)"[^>]*>', page)
        for division_match in divisions:
            url = urllib.parse.urljoin(self.standings_url, division_match.group('url'))
            division = division_match.group('name')

            page = REQ.get(url)

            tables = re.finditer(r'>(?P<title>[^<]*)</[^>]*>\s*(?P<html><table[^>]*>.*?</table>)', page, re.DOTALL)
            for table_match in tables:
                title = table_match.group('title')
                table = parsed_table.ParsedTable(table_match.group('html'))

                d = problems_info.setdefault('division', OrderedDict())
                if division not in d:
                    d = d.setdefault(division, [])
                    already_added = set()
                    for c in table.header.columns:
                        short = c.value
                        if 'colspan' in c.attrs and short not in already_added:
                            d.append({'short': short})
                            already_added.add(short)

                for r in table:
                    row = OrderedDict()
                    problems = row.setdefault('problems', {})
                    for key, value in r.items():
                        key = key.replace('&nbsp', ' ').strip()
                        if not key:
                            continue
                        if isinstance(value, list):
                            status = ''.join(v.value for v in value)
                            if not status:
                                continue
                            partial = not bool(re.match(r'^[\*]+$', status))
                            problems[key] = {
                                'partial': partial,
                                'result': 1000 / len(already_added) * status.count('*') / len(status),
                                'status': status,
                            }
                        elif key == 'Score':
                            row['solving'] = int(value.value)
                        else:
                            row[key.lower()] = value.value.replace('&nbsp', ' ').strip()
                    row['member'] = f'{row["name"]}, {row["country"]}'
                    row['division'] = division
                    row['title'] = title.strip().strip(':')
                    result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='First Contest',
        url='http://usaco.org/',
        key='First Contest 2019',
        start_time=datetime.strptime('Dec 20 2019', '%b %d %Y'),
        standings_url=None,
    )
    pprint(statictic.get_standings())
