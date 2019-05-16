#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ, DOT, SPACE, BaseModule, parsed_table

import re


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        if not self.standings_url:
            return {}

        page = REQ.get(self.standings_url)

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)
        mapping_key = {
            'rank': 'place',
            'rankl': 'place',
            'party': 'member',
            'solved': 'solving',
        }
        result = {}
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                c = v.attrs['class'].split()[0]
                if c in ['problem', 'ioiprob']:
                    v = v.value
                    if v != DOT:
                        p = problems.setdefault(k, {})
                        if SPACE in v:
                            v, t = v.split(SPACE, 1)
                            p['time'] = t
                        p['result'] = v
                else:
                    c = mapping_key.get(c, c)
                    row[c] = v.value
            if 'penalty' not in row:
                row['member'] = re.sub(r'\s*\([^\)]*\)\s*$', '', row['member']) + ' ' + season
                solved = [p for p in list(problems.values()) if p['result'] == '100']
                row['solved'] = {'solving': len(solved)}
            result[row['member']] = row
        standings = {
            'result': result,
        }
        return standings
