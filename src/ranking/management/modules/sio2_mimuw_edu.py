#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import re
from urllib.parse import urljoin

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None, statistics=None):

        def parse_problems_infos():
            problem_url = self.standings_url.replace('/ranking', '/p')
            page = REQ.get(problem_url)

            match = re.search(r'<h1[^>]*>[^<]*</h1>(\s*<[^/][^>]*>)*\s*(?P<table><table[^>]*>.*?</table>)',
                              page,
                              re.DOTALL)
            if not match:
                raise ExceptionParseStandings('Not found problems table')
            table = parsed_table.ParsedTable(html=match.group('table'), ignore_wrong_header_number=False)
            skip = False
            problems_infos = collections.OrderedDict()
            for r in table:
                if isinstance(r, parsed_table.ParsedTableRow):
                    runda = re.sub(r'\s*\(.*\)\s*$', '', r.columns[0].value).strip()
                    runda = runda.strip('.')
                    skip = runda.lower() not in self.name.lower()
                    continue

                if skip:
                    continue

                problem_info = {}
                for k, vs in list(r.items()):
                    if isinstance(vs, list):
                        v = ' '.join([v.value for v in vs]).strip()
                    else:
                        v = vs.value
                    if not k:
                        problem_info['short'] = v
                    elif k in ('Nazwa', 'Name'):
                        match = re.search(r'\[(?P<letter>[^\]]+)\]$', v)
                        if match:
                            problem_info['_letter'] = match.group('letter')
                        problem_info['name'] = v
                        href = vs.column.node.xpath('.//a/@href')
                        if href:
                            problem_info['url'] = urljoin(problem_url, href[0])
                if problem_info:
                    problems_infos[problem_info['short']] = problem_info
            return problems_infos

        problems_infos = parse_problems_infos()

        result = {}
        full_scores = set()

        page = 1
        while page is not None:
            content = REQ.get(self.standings_url + f'?page={page}')

            matches = re.finditer(r'<a[^>]*href="[^"]*\?page=(?P<page>[0-9]+)"[^>]*>', content)
            next_page = None
            for match in matches:
                p = int(match.group('page'))
                if p > page and (next_page is None or p < next_page):
                    next_page = p
            page = next_page

            mapping = {'Użytkownik': 'User'}
            table = parsed_table.ParsedTable(
                html=content,
                xpath="//table[contains(@class,'table-ranking')]//tr",
                header_mapping=mapping,
            )
            for r in table:
                row = collections.OrderedDict()
                problems = row.setdefault('problems', {})
                row['solving'] = 0
                for k, v in list(r.items()):
                    if k == '#':
                        row['place'] = v.value
                    elif k == 'User':
                        row['name'] = v.value
                        rid = v.row.node.xpath('@id')[0]
                        match = re.match('^ranking_row_(?P<id>[0-9]+)$', rid)
                        member = match.group('id')
                        row['member'] = member
                    elif k in problems_infos and v.value:
                        problems[k] = {'result': v.value}
                        value = as_number(v.value)
                        row['solving'] += value
                        if 'submission--OK100' in v.attrs.get('class', ''):
                            problems_infos[k].setdefault('full_score', value)
                            full_scores.add(value)
                if not problems:
                    continue
                result[row['member']] = row

        last = None
        for idx, row in enumerate(sorted(result.values(), key=lambda r: -r['solving']), start=1):
            if last != row['solving']:
                last = row['solving']
                rank = idx
            row['place'] = rank

        problems_infos = list(problems_infos.values())
        if all('_letter' in p for p in problems_infos):
            problems_infos.sort(key=lambda p: p['_letter'])
        for p in problems_infos:
            p.pop('_letter', None)

        ret = {
            'result': result,
            'problems': problems_infos,
        }

        if len(full_scores) == 1:
            ret['default_problem_full_score'] = list(full_scores)[0]

        return ret
