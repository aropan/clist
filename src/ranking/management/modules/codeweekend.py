# -*- coding: utf-8 -*-

from collections import OrderedDict
from datetime import timedelta
from urllib.parse import urljoin

from django.utils import timezone

from clist.templatetags.extras import as_number, get_item
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        api_url = get_item(self.resource, 'info.statistics.api_url')
        data = REQ.get(urljoin(api_url, 'scoreboard'), return_json=True)
        season = self.get_season()

        if self.end_time + timedelta(days=30) < timezone.now():
            raise ExceptionParseStandings('Contest is long over')

        problems_infos = OrderedDict()
        result = {}
        for team in data.pop('teams'):
            name = team.pop('user_display_name')
            member = f'{name} {season}'
            r = result.setdefault(member, {})
            r['name'] = name
            r['member'] = member
            r['solving'] = team.pop('total_score')
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

            members = team.pop('team_members').split(',')
            if members:
                r['_members'] = [{'name': m.strip()} for m in members]

        for r in result.values():
            for short, problem in r['problems'].items():
                if problems_infos[short]['max_score'] == problem['raw_score']:
                    problem['max_score'] = True

        last_score = None
        last_rank = None
        for rank, r in enumerate(sorted(result.values(), key=lambda x: -x['solving']), start=1):
            if last_score != r['solving']:
                last_score = r['solving']
                last_rank = rank
            r['place'] = last_rank

        standings = {
            'result': result,
            'url': urljoin(self.url, 'scoreboard'),
            'problems': list(problems_infos.values()),
        }
        return standings
