# -*- coding: utf-8 -*-

import hashlib
from collections import OrderedDict
from datetime import timedelta
from urllib.parse import urljoin

from django.utils import timezone

from clist.templatetags.extras import as_number, get_item, slug
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if self.end_time + timedelta(days=30) < timezone.now():
            raise ExceptionParseStandings('Contest is long over')

        api_urls = get_item(self.info, 'standings.api_urls')
        divisions_problems = OrderedDict()
        divisions_order = []
        result = {}
        for division in ('live', 'day2', 'day1', 'upsolving'):
            api_url = api_urls.get(division)
            if not api_url:
                continue

            try:
                data = REQ.get(api_url, return_json=True)
            except FailOnGetResponse:
                continue

            problems_infos = OrderedDict()
            rows = []
            for team in data.pop('teams'):
                name = team.pop('user_display_name')
                team_members = team.pop('team_members')
                member = name + ' ' + hashlib.shake_128(team_members.encode()).hexdigest(5)
                member = slug(member)
                r = result.setdefault(member, {})
                r['name'] = name
                r['member'] = member
                members = team_members.split(',')
                if members:
                    r['_members'] = [{'name': m.strip()} for m in members]

                r = r.setdefault('_division_addition', {}).setdefault(division, {})
                r['solving'] = team.pop('total_score')
                r['division'] = division
                problems = r.setdefault('problems', {})
                for task in team.pop('tasks'):
                    score = task.pop('relative_score')
                    short = str(task.pop('task_id'))

                    if short not in problems_infos:
                        problem_info = {
                            'short': short,
                            'url': urljoin(self.url, f'scoreboard#/visualizer?task_id={short}'),
                        }
                        problems_infos[short] = problem_info
                    if score is None:
                        continue
                    p = problems.setdefault(short, {})
                    p['result'] = score
                    p['submission_id'] = task.pop('submission_id')
                    p['raw_score'] = as_number(task.pop('raw_score'))
                    p['time_in_seconds'] = task.pop('seconds_since_start')
                    p['time'] = self.to_time(p['time_in_seconds'], 3)

                    problem_info = problems_infos[short]
                    problem_info['max_score'] = max(problem_info.get('max_score', 0), p['raw_score'])

                    p['url'] = problem_info['url'] + f'&submission_id={p["submission_id"]}'

                rows.append(r)

            for r in rows:
                for short, problem in r['problems'].items():
                    if problems_infos[short]['max_score'] == problem['raw_score']:
                        problem['max_score'] = True

            last_score = None
            last_rank = None
            for rank, r in enumerate(sorted(rows, key=lambda x: -x['solving']), start=1):
                if last_score != r['solving']:
                    last_score = r['solving']
                    last_rank = rank
                r['place'] = last_rank

            divisions_problems[division] = list(problems_infos.values())
            divisions_order.append(division)
        problems = {'division': divisions_problems}

        fields_types = {'delta_rank': ['delta'], 'delta_score': ['delta']}
        for division, base in (('live', 'day1'), ('day2', 'day1'), ('day1', 'live'), ('day1', 'day2'),
                               ('upsolving', 'day2')):
            for r in result.values():
                division_r = r['_division_addition'].get(division, {})
                base_r = r['_division_addition'].get(base, {})
                if not division_r or not base_r:
                    continue
                delta_score = division_r['solving'] - base_r['solving']
                delta_rank = base_r['place'] - division_r['place']
                if division == 'day1':
                    delta_score = -delta_score
                    delta_rank = -delta_rank
                division_r['delta_score'] = delta_score
                division_r['delta_rank'] = delta_rank

        if result:
            division = next(iter(divisions_problems))
            for r in result.values():
                r.update(r['_division_addition'].pop(division, {}))
                r['_division_addition'][division] = {}

        standings = {
            'result': result,
            'url': urljoin(self.url, 'scoreboard'),
            'fields_types': fields_types,
            'problems': problems,
        }
        return standings
