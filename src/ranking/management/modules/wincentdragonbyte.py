#!/usr/bin/env python3

import re
from collections import OrderedDict

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):

        if not self.standings_url:
            raise ExceptionParseStandings('no standings url')

        standings_page = REQ.get(self.standings_url)

        match = re.search(r'<table[^>]*id="scoreboard"[^>]*>.*?</table>', standings_page, re.DOTALL)
        if not match:
            raise ExceptionParseStandings('can not find standings table')
        table = parsed_table.ParsedTable(match.group())

        result = {}
        problems_infos = OrderedDict()
        for row in table:
            handle = row.pop('username').value
            r = result.setdefault(handle, OrderedDict({'member': handle}))
            r['place'] = as_number(row.pop('rank').value.rstrip('.'))
            r['solving'] = as_number(row.pop('score').value)
            r['time'] = row.pop('time').value
            problems = r.setdefault('problems', OrderedDict())
            for short, cell in row.items():
                value = cell.value
                problems_infos.setdefault(short, {'short': short}) 
                if not value:
                    continue
                problem = problems.setdefault(short, {})
                if ' ' not in value:
                    problem['result'] = as_number(value)
                else:
                    attempts, value = value.split()
                    problem['result'] = as_number(value)
                    problem['attempts'] = as_number(attempts.rstrip(':'))
            if not problems:
                result.pop(handle)
                continue

        ret = {
            'result': result,
            'problems': list(problems_infos.values()),
        }
        return ret