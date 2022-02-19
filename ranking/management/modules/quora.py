#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import csv

import arrow

from ranking.management.modules.common import REQ, BaseModule, parsed_table


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        result = {}

        result = {}
        problems_info = collections.OrderedDict()

        def process_kv(row, k, v):
            if k == 'Rank':
                row['place'] = v
            elif k == 'Username':
                row['member'] = v
            elif k == 'User':
                if 'member' not in row:
                    row['member'] = v + ' ' + season
                row['name'] = v
            elif k == 'Last valid submission':
                delta = arrow.get(v, ['YYYY-MM-DD H:mm:ss']) - self.start_time
                row['penalty'] = self.to_time(delta, 3)
            elif k in ['Global']:
                row['solving'] = v
            else:
                problems = row.setdefault('problems', {})
                if k not in problems_info:
                    problems_info[k] = {'short': k, 'full_score': 100}
                if float(v) > 1e-9:
                    p = problems.setdefault(k, {})
                    p['result'] = v
                    p['partial'] = float(v) + 1e-9 < problems_info[k]['full_score']

        filepath = self.info.get('standings_csv_filepath_')
        if filepath:
            season = self.get_season()

            with open(filepath, 'r') as fo:
                data = csv.DictReader(fo)
                last, place = None, None
                for idx, r in enumerate(data, start=1):
                    row = collections.OrderedDict()
                    for k, v in r.items():
                        process_kv(row, k, v)
                    score = (row['solving'], row['penalty'])
                    if last != score:
                        last = score
                        place = idx
                    row['place'] = place
                    result[row['member']] = row
        elif self.standings_url:
            page = REQ.get(self.standings_url)
            problems_info = collections.OrderedDict()
            table = parsed_table.ParsedTable(page)
            for r in table:
                row = collections.OrderedDict()
                for k, v in r.items():
                    process_kv(row, k, v.value)
                result[row['member']] = row

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
            'hidden_fields': ['medal'],
        }
        return standings
