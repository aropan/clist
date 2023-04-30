# -*- coding: utf-8 -*-

import re
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        url = self.standings_url.replace('/contests/', '/api/v0/contests/')
        data = REQ.get(url, return_json=True)
        problems_info = OrderedDict()
        result = OrderedDict()
        has_hidden = False
        for row in data['rows']:
            handle = str(row['participant']['scope_user']['id'])
            if hasattr(self, 'prefix_handle'):
                handle = self.prefix_handle + handle
            r = result.setdefault(handle, {'member': handle})
            r['name'] = row['participant']['scope_user']['title']

            division = 'unofficial' if re.search(r'^(\*|\[[^\]]*\*\])', r['name']) else 'official'
            r['division'] = division

            upsolving = 'place' not in row
            if not upsolving:
                r['place'] = row['place']
                r['solving'] = row['score']
                r['penalty'] = row['penalty']
            else:
                r['_no_update_n_contests'] = bool('place' not in r)

            problems = r.setdefault('problems', {})
            for cell in row.get('cells', []):

                divisions = problems_info.setdefault('division', {})
                if division not in divisions:
                    divisions[division] = [{'short': problem['code']} for problem in data['columns']]
                short = problems_info['division'][division][cell['column']]['short']

                problem = problems.setdefault(short, {})
                if upsolving:
                    problem = problem.setdefault('upsolving', {})
                attempt = cell['attempt']
                if cell['verdict'] == 'accepted':
                    if attempt == 1:
                        problem['result'] = '+'
                    else:
                        problem['result'] = f'+{attempt - 1}'
                elif cell['verdict'] == 'rejected':
                    problem['result'] = f'-{attempt}'
                elif not cell['verdict']:
                    has_hidden = True
                    problem['result'] = f'?{attempt}'
                if 'time' in cell:
                    problem['time_in_seconds'] = cell['time']
                    problem['time'] = self.to_time(cell['time'] // 60, 2)

        standings = dict()

        if len(problems_info.get('division', {})) == 1:
            problems_info = list(problems_info['division'].values())[0]
        else:
            previous_values = dict()
            for row in result.values():
                if 'place' not in row:
                    continue
                division = row['division']
                values = previous_values.setdefault(division, {})
                values.setdefault('idx', 0)
                values['idx'] += 1
                score = (row['solving'], row['penalty'])
                if values.get('score') != score:
                    values['rank'] = values['idx']
                    values['score'] = score
                row['place'] = values['rank']
            options = standings.setdefault('options', {})
            options['medals_divisions'] = ['official']

        standings.update({
            'result': result,
            'problems': problems_info,
            'has_hidden': has_hidden,
        })
        return standings
