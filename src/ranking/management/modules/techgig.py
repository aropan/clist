#!/usr/bin/env python3

import os
import re
from datetime import timedelta

from django.utils.timezone import now

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.name.endswith('Finale'):
            raise ExceptionParseStandings('not final')

        contest_url = (
            f'https://www.techgig.com/codegladiators{self.end_time.year}'
            if self.end_time + timedelta(days=200) < now() else
            'https://www.techgig.com/codegladiators'
        )
        standings_url = f'{contest_url}/finaleleaderboard'

        season = self.get_season()

        with REQ.with_proxy(
            time_limit=3,
            n_limit=100,
            filepath_proxies=os.path.join(os.path.dirname(__file__), '.techgig.proxies'),
            connect=lambda req: req.get(standings_url),
        ) as req:
            page = req.proxer.get_connect_ret()

        html_table = re.search('<table[^>]*>.*?</table>', page, re.MULTILINE | re.DOTALL)
        if not html_table:
            raise ExceptionParseStandings('Not found html table')
        mapping = {
            'Rank': 'place',
            'Name': 'name',
            'Language': 'language',
        }
        table = parsed_table.ParsedTable(html_table.group(0), header_mapping=mapping)

        result = {}
        for r in table:
            row = dict()
            for k, v in r.items():
                if v.value:
                    row[k] = v.value
            if 'member' not in row:
                row['member'] = f'{row["name"]} {season}'
            result[row['member']] = row

        ret = {
            'result': result,
            'url': standings_url,
            'contest_url': contest_url,
        }
        options = ret.setdefault('options', {})
        options['medals'] = [
            {"name": "gold", "count": 1},
            {"name": "silver", "count": 1},
            {"name": "bronze", "count": 1},
            {"name": "honorable", "count": 2},
        ]
        return ret
