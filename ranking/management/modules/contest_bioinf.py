#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from pprint import pprint  # noqa

import coloredlogs
import pytz

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            raise ExceptionParseStandings('Not set stnadings url')
        is_final = self.name.lower().startswith('final round')
        now = datetime.utcnow().replace(tzinfo=pytz.utc)
        if not is_final and self.end_time + timedelta(days=3) < now:
            raise ExceptionParseStandings('Too late')

        page = REQ.get(self.standings_url)

        html_table = re.search('<table[^>]*>.*?</table>', page, re.MULTILINE | re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table, as_list=True, ignore_wrong_header_number=False)

        problems_info = OrderedDict()

        result = {}
        season = self.get_season()
        advanced = False
        for r in table:
            if isinstance(r, parsed_table.ParsedTableRow):
                if re.search(r'qualification\s*threshold', r.columns[0].value, re.I):
                    advanced = True
                    for row in result.values():
                        row['advanced'] = True
                continue
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            if advanced:
                row['advanced'] = False
            pid = 0
            for k, v in r:
                if k == '#':
                    row['place'] = v.value
                elif k == 'Name':
                    row['name'] = v.value
                elif k.startswith('Total'):
                    row['solving'] = v.value
                elif '_top_column' in v.header.attrs:
                    problem_key = str(pid)
                    if problem_key not in problems_info:
                        name = v.header.attrs['_top_column'].value
                        p_info = {'code': problem_key}
                        p_info_regex = r'^(?P<name>.*)\s+\(?(?P<score>[0-9]{2,})\)?$'
                        match = re.search(p_info_regex, name)
                        if match:
                            name = match.group('name').strip()
                        match = re.search(p_info_regex, k)
                        if match:
                            p_info['subname'] = match.group('name').strip()
                            p_info['full_score'] = int(match.group('score'))
                        p_info['name'] = name
                        href = v.header.node.xpath('a/@href')
                        if href:
                            p_info['suburl'] = href[0]
                            p_info['url'] = href[0]
                        problems_info[problem_key] = p_info

                    if v.value:
                        try:
                            val = float(v.value)
                            if val:
                                p = problems.setdefault(problem_key, {})
                                p['result'] = v.value

                                full_score = problems_info[problem_key].get('full_score')
                                if full_score is not None:
                                    p['partial'] = val < full_score
                                else:
                                    style = v.attrs.get('style')
                                    if style:
                                        if 'yellow' in style:
                                            p['partial'] = True
                                        elif 'lightgreen' in style:
                                            p['partial'] = False
                                            if full_score is None:
                                                problems_info[problem_key]['full_score'] = int(round(val, 0))
                        except ValueError:
                            pass
                    pid += 1
                else:
                    row.setdefault('_info', {})[k] = v.value

            if not problems:
                continue

            handle = row['name'] + ' ' + season
            row['member'] = handle
            if handle in result:
                continue
            result[handle] = row

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }

        if is_final:
            standings['options'] = {'medals': [{'name': k, 'count': 1} for k in ('gold', 'silver', 'bronze')]}

        return standings
