# -*- coding: utf-8 -*-

from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        url = self.standings_url.replace('/contests/', '/api/v0/contests/')
        data = REQ.get(url, return_json=True)

        problems_infos = OrderedDict()
        for idx, problem in enumerate(data['columns']):
            short = problem['code']
            problems_infos[idx] = {'short': short}

        result = {}
        has_hidden = False
        for row in data['rows']:
            handle = str(row['participant']['scope_user']['id'])
            if hasattr(self, 'prefix_handle'):
                handle = self.prefix_handle + handle
            r = result.setdefault(handle, {'member': handle})
            r['name'] = row['participant']['scope_user']['title']
            upsolving = 'place' not in row
            if not upsolving:
                r['place'] = row['place']
                r['solving'] = row['score']
                r['penalty'] = row['penalty']
            else:
                r['_no_update_n_contests'] = bool('place' not in r)

            problems = r.setdefault('problems', {})
            for cell in row.get('cells', []):
                short = problems_infos[cell['column']]['short']
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

        standings = {
            'result': result,
            'problems': list(problems_infos.values()),
            'has_hidden': has_hidden,
        }
        return standings
