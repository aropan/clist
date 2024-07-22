#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
from collections import OrderedDict, defaultdict

from clist.templatetags.extras import as_number, get_item, toint
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.standings_url:
            raise ExceptionParseStandings('not standings url')

        problems_infos = OrderedDict()

        def get_results(standings_url, division_data):
            page = REQ.get(standings_url)

            page_format = division_data.get('format')
            problems_results = defaultdict(lambda: defaultdict(int))
            if page_format == 'json':
                data = json.loads(page)
                scores_field = None
                if 'problems' in data:
                    scores_field = 'problem'
                elif 'tournaments' in data:
                    scores_field = 'tournament'

                if 'columns' in data and 'rows' in data:
                    columns = data.pop('columns')
                    data['teams'] = [dict(zip(columns, row['values'])) for row in data.pop('rows')]
                else:
                    columns = None

                if scores_field:
                    scores_fields_mapping = {'submission': 'T', 'request': 'R'}
                    scores_mapping = OrderedDict()
                    for score in data[f'{scores_field}s']:
                        name = str(score[f'{scores_field}Id'])
                        scores_mapping[name] = scores_fields_mapping.get(name, name.split(':')[-1])

                table = []
                for team in data['teams']:
                    row = OrderedDict()
                    row['name'] = get_item(team, 'team.teamName') or get_item(team, 'team')
                    place = get_item(team, '#')
                    if place:
                        row['place'] = place
                    if 'score' in team:
                        row['solving'] = team['score']
                    country = get_item(team, 'team.customData.country')
                    if country:
                        row['country'] = country
                    if scores_field:
                        problems = row.setdefault('_scores', OrderedDict())
                        scores = team[f'{scores_field}s']
                        for field, out in scores_mapping.items():
                            if field in scores:
                                problems[out] = as_number(scores.get(field, {}).get('score'))
                    if division_data.get('remaining_fields_are_problems'):
                        problems = row.setdefault('problems', {})
                        keys = columns or team.keys()
                        for k in keys:
                            if k in {'#', 'team'} or k not in team:
                                continue
                            if k not in problems_infos:
                                problems_infos[k] = {'short': k}
                            v = as_number(team[k])
                            if v is None:
                                continue
                            problems[k] = {'result': v}
                            if isinstance(v, (int, float)):
                                problems_results[k][v] += 1
                    table.append(row)
            else:
                mapping = {
                    'Rank': 'place',
                    'Position': 'place',
                    '': 'place',
                    'Score': 'solving',
                    'score': 'solving',
                    'Total Score': 'solving',
                    'Team': 'name',
                    'name': 'name',
                    'Username': 'name',
                    'Team Name': 'name',
                    'score + unspent LAM': 'unspent_lam',
                }
                xpath = division_data.get('xpath', '//table//tr')
                table = parsed_table.ParsedTable(html=page, header_mapping=mapping, xpath=xpath)

            season = self.get_season()
            ret = {}
            was_place = False
            for r in table:
                row = OrderedDict()
                for k, v in r.items():
                    was_place = was_place or k == 'place'
                    if isinstance(v, parsed_table.ParsedTableValue):
                        v = v.value
                    if k == 'name':
                        row['name'] = v
                        row['member'] = f'{v} {season}'
                    else:
                        if k in {'place', 'solving'} and isinstance(v, str):
                            v = as_number(v.replace(',', ''))
                        row[k] = v
                if division_data.get('borda_count') and 'problems' in row:
                    solving = 0
                    for short, problem in row['problems'].items():
                        v = problem['result']
                        if isinstance(v, (int, float)):
                            problem['status'] = f'#{v}'
                            v += problems_results[short][v] - 1
                            v = len(table) - v
                            problem['result'] = v
                            solving += v
                    if 'solving' not in row:
                        row['solving'] = solving
                ret[row['member']] = row

            if not was_place:
                place = None
                last = None
                for idx, row in enumerate(sorted(ret.values(), key=lambda r: r['solving'], reverse=True), start=1):
                    if row['solving'] != last:
                        last = row['solving']
                        place = idx
                    row['place'] = place
            return ret

        fields_types = {}
        results = {}

        divisions = self.info.get('standings', {}).get('divisions', [])
        divisions_order = []
        divisions_fields_types = defaultdict(OrderedDict)
        for division_data in divisions:
            division = division_data['name']
            division_results = get_results(division_data['standings_url'], division_data)

            medals = []
            for medal in division_data.get('medals', []):
                medals += [medal['name']] * medal['count']

            for handle, result in division_results.items():
                default = OrderedDict(member=result.pop('member'), name=result['name'])
                row = results.setdefault(handle, default)

                place_as_int = toint(result.get('place'))
                if place_as_int is not None and place_as_int <= len(medals):
                    medal = medals[place_as_int - 1]
                    result['medal'] = medal
                    result['_medal_title_field'] = '_medal_title'
                    result['_medal_title'] = f'{division.title()} {medal.title()}'

                scores = result.pop('_scores', {})

                if divisions_order:
                    prev_division = divisions_order[-1]
                    reverse_mapping = {'place': 'rank', 'solving': 'score'}
                    for k, v in list(result.items()):
                        if k in 'medal' and k not in row:
                            for f in 'medal', '_medal_title_field', '_':
                                row[f] = result[f]
                        if k in {'name', 'medal'} or k.startswith('_'):
                            continue
                        if k in {'place', 'solving'}:
                            new_k = f'{division}_{reverse_mapping.get(k, k)}'
                            row[new_k] = v
                            try:
                                prev_val = row['_division_addition'][prev_division][k]

                                ref_k = f'{prev_division}_{reverse_mapping.get(k, k)}'
                                result[ref_k] = prev_val
                                divisions_fields_types[division].setdefault(ref_k, [])

                                val = float(prev_val) - float(v)
                                val = int(val) if int(val) == val else val
                                if k == 'place':
                                    val = -val
                                field = f'{new_k}_delta'
                                row[field] = val
                                field_types = fields_types.setdefault(field, [])
                                if 'delta' not in field_types:
                                    field_types.append('delta')

                                field = f'{ref_k}_delta'
                                result[field] = val
                                field_types = divisions_fields_types[division].setdefault(field, [])
                                if 'delta' not in field_types:
                                    field_types.append('delta')
                            except Exception:
                                pass
                else:
                    row.update(scores)
                    row.update(result)

                division_addition = row.setdefault('_division_addition', {}).setdefault(division, OrderedDict())
                division_addition.update(scores)
                division_addition.update(result)

            divisions_order.append(division)

        for value in results.values():
            for division, row in value.get('_division_addition', {}).items():
                for k, v in row.items():
                    field_types = divisions_fields_types[division].setdefault(k, [])
                    field_type = type(v).__name__
                    if field_type not in field_types:
                        field_types.append(field_type)

        for idx, division_data in enumerate(divisions):
            division = division_data['name']
            disable_fields = division_data.get('disable_fields', [])
            for field in disable_fields:
                divisions_fields_types[division].pop(field, None)
            if idx == 0:
                for row in results.values():
                    for field in disable_fields:
                        row.pop(field, None)

        return dict(
            result=results,
            fields_types=fields_types,
            divisions_addition={k: dict(fields=list(fields_types.keys()), fields_types=fields_types)
                                for k, fields_types in divisions_fields_types.items()},
            divisions_order=divisions_order,
            problems=list(problems_infos.values()),
        )
