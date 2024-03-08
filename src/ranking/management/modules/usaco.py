#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


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
                if (month in name or self.name.lower() in name) and str(self.start_time.year) in name:
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

    def get_standings(self, users=None, statistics=None):

        def parse_problems(page, full=False):
            matches = re.finditer(r'''
                <div[^>]*class=['"]panel\s*historypanel['"][^>]*>\s*
                <div[^>]*>\s*<h[^>]*>(?P<index>[^<]*)</h[^>]*>\s*</div>\s*
                <div[^>]*>(\s*<[^>]*>)*(?P<name>[^<]+)
                (\s*<[^>]*>)*\s*<a[^>]*href=["'](?P<url>[^"']*)["'][^>]*>
            ''', page, re.VERBOSE)

            problems = []
            problemsets = []

            prev_index = None
            for match in matches:
                index = match.group('index')
                if prev_index and index <= prev_index:
                    if full:
                        problemsets.append(problems)
                        problems = []
                    else:
                        break
                prev_index = index
                url = urllib.parse.urljoin(self.standings_url, match.group('url'))
                cpid = re.search('cpid=([0-9]+)', url).group(1)
                problems.append({
                    'short': str(len(problems) + 1),
                    'code': cpid,
                    'name': match.group('name'),
                    'url': url,
                })

            if problems:
                problemsets.append(problems)

            return problemsets if full else problems

        page = REQ.get(self.standings_url)
        divisions = list(re.finditer('<a[^>]*href="(?P<url>[^"]*data[^"]*_(?P<name>[^_]*)_results.html)"[^>]*>', page))
        descriptions = []
        prev_span = None
        for division_match in divisions:
            curr_span = division_match.span()
            if prev_span is not None:
                descriptions.append(page[prev_span[1]:curr_span[0]])
            prev_span = curr_span
        if prev_span is not None:
            descriptions.append(page[prev_span[1]:])

        problems_info = OrderedDict()
        match = re.search('''<a[^>]*href=["'](?P<href>[^"']*page=[a-z0-9]+problems)["'][^>]*>''', page)
        if match:
            url = urllib.parse.urljoin(self.standings_url, match.group('href'))
            page = REQ.get(url)
            problemsets = parse_problems(page, full=True)
            assert len(divisions) == len(problemsets)
        else:
            problemsets = None

        result = {}
        d0_set = set()
        for division_idx, (division_match, description) in enumerate(zip(divisions, descriptions)):
            division = division_match.group('name')

            d_problems = parse_problems(description) if problemsets is None else problemsets[division_idx]
            division_info = problems_info.setdefault('division', OrderedDict())
            division_info[division] = d_problems

            d0 = division[0].upper()
            assert d0 not in d0_set
            d0_set.add(d0)
            for p in d_problems:
                p['short'] = d0 + p['short']

            url = urllib.parse.urljoin(self.standings_url, division_match.group('url'))
            page = REQ.get(url)

            tables = re.finditer(r'>(?P<title>[^<]*)</[^>]*>\s*(?P<html><table[^>]*>.*?</table>)', page, re.DOTALL)
            for table_match in tables:
                title = table_match.group('title')
                table = parsed_table.ParsedTable(table_match.group('html'))

                for r in table:
                    row = OrderedDict()
                    problems = row.setdefault('problems', {})
                    solved = 0
                    idx = 0
                    for key, value in r.items():
                        key = key.replace('&nbsp', ' ').strip()
                        if not key:
                            continue
                        if isinstance(value, list):
                            status = ''.join(v.value for v in value)
                            idx += 1
                            if not status:
                                continue
                            partial = not bool(re.match(r'^[\*]+$', status))
                            solved += not partial
                            problems[d0 + str(idx)] = {
                                'partial': partial,
                                'result': 1000 / len(d_problems) * status.count('*') / len(status),
                                'status': status,
                            }
                        elif key == 'Score':
                            row['solving'] = int(value.value)
                        else:
                            row[key.lower()] = value.value.replace('&nbsp', ' ').strip()
                    handle = f'{row["name"]}, {row["country"]}'
                    row['member'] = handle
                    row['division'] = division
                    row['list'] = [title.strip().strip(':')]
                    row['solved'] = {'solving': solved}
                    row.setdefault('_division_addition', {})[row['division']] = deepcopy(row)

                    if handle in result:
                        result_row = result[handle]
                        for field in ['problems', '_division_addition']:
                            result_row[field].update(row[field])
                        for val in row['list']:
                            if val not in result_row['list']:
                                result_row['list'].append(val)
                        row = result_row
                    result[handle] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
            'hidden_fields': ['list'],
        }
        return standings


