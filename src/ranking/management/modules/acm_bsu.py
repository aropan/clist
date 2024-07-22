#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import re
from datetime import timedelta
from pprint import pprint

from django.utils.timezone import now

from clist.templatetags.extras import as_number
from ranking.management.modules.common import DOT, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None, statistics=None, **kwargs):
        year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
        season = f'{year}-{year + 1}'
        is_challenge = bool(re.search(r'\bchallenge\b', self.name, re.I))
        is_running = now() < self.end_time + timedelta(minutes=30)
        has_provisional = False

        result = {}
        try:
            page = REQ.get(self.standings_url)
        except FailOnGetResponse as e:
            if e.code == 403:
                raise ExceptionParseStandings('Forbidden')
            raise e
        table = parsed_table.ParsedTable(html=page, xpath="//table[@class='ir-contest-standings']//tr")
        problems_info = collections.OrderedDict()
        has_plus = False
        for r in table:
            row = collections.OrderedDict()
            problems = row.setdefault('problems', {})
            ioi_total_fields = ['Sum', 'Сумма']
            # ioi_style = any((f in r for f in ioi_total_fields))
            for k, v in list(r.items()):
                classes = v.attrs['class'].split()
                if 'ir-column-contestant' in classes:
                    row['member'] = v.value + ' ' + season
                    row['name'] = v.value
                elif 'ir-column-place' in classes:
                    row['place'] = v.value
                elif 'ir-column-penalty' in classes:
                    row['penalty'] = int(v.value)
                elif 'ir-problem-count' in classes or k in ioi_total_fields:
                    row['solving'] = int(v.value)
                elif len(k.split()[0]) == 1:
                    letter = k.split()[0]
                    problems_info[letter] = {'short': letter}
                    if v.value == DOT:
                        continue
                    p = problems.setdefault(letter, {})
                    values = v.value.replace('−', '-').split(' ')
                    p['result'] = values[0]
                    if p['result'].startswith('+'):
                        has_plus = True
                    elif not p['result'].startswith('-') and v.column.node.xpath('.//*[@class="ir-rejected"]'):
                        p['partial'] = True
                    if len(values) > 1:
                        p['time'] = values[1]
                else:
                    row[k.lower()] = v.value

            member = row['member']
            if member in result:
                idx = 0
                while member + f'-{idx}' in result:
                    idx += 1
                member += f'-{idx}'
                row['member'] = member

            if is_challenge:
                stats = (statistics or {}).get(member, {})
                for k in self.info.get('fields', []):
                    if k not in row and k in stats:
                        row[k] = stats[k]

                if 'provisional_rank' not in row or is_running:
                    row['provisional_rank'] = as_number(row['place'])
                row['delta_rank'] = row['provisional_rank'] - as_number(row['place'])
                if 'provisional_score' not in row or is_running:
                    row['provisional_score'] = row['solving']
                row['delta_score'] = row['solving'] - row['provisional_score']
                has_provisional |= bool(row['delta_rank']) or bool(row['delta_score'])

                if 'best_score' not in row:
                    row['best_score'] = row['solving']
                elif is_running:
                    row['best_score'] = max(row['best_score'], row['solving'])

            if not (problems or (is_challenge and stats)):
                continue

            if users and row['member'] not in users:
                continue

            result[member] = row

        if not has_plus:
            for row in result.values():
                solved = 0
                for p in row['problems'].values():
                    if p.get('partial'):
                        continue
                    try:
                        score = float(p['result'])
                        if score > 0:
                            solved += 1
                    except Exception:
                        pass
                row['solved'] = {'solving': solved}

        hidden_fields = []
        fields_types = {}
        if is_challenge:
            fields_types.update({'delta_rank': ['delta'], 'delta_score': ['delta']})
            if not has_provisional:
                hidden_fields.extend(['provisional_rank', 'delta_rank', 'provisional_score', 'delta_score'])
            if not is_running:
                hidden_fields.extend(['best_score'])

        standings = {
            'result': result,
            'url': self.standings_url,
            'hidden_fields': hidden_fields,
            'fields_types': fields_types,
            'problems': list(problems_info.values()),
            'problems_time_format': '{H}:{m:02d}',
        }
        return standings


