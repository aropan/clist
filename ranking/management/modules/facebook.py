#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
import tqdm
from pprint import pprint
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):
    API_GRAPH_URL_ = 'https://www.facebook.com/api/graphql/'

    def get_standings(self, users=None, statistics=None):
        page = REQ.get(self.standings_url)
        match = re.search(r'\["LSD",\[\],{"token":"(?P<token>[^"]*)"', page)
        lsd_token = match.group('token')

        def query(name, variables):
            ret = REQ.get(
                self.API_GRAPH_URL_,
                post={
                    'lsd': lsd_token,
                    'fb_api_caller_class': 'RelayModern',
                    'fb_api_req_friendly_name': name,
                    'variables': json.dumps(variables),
                    'doc_id': self.info['parse']['scoreboard_ids'][name],
                },
            )
            return json.loads(ret)

        scoreboard_data = query('CodingCompetitionsContestScoreboardQuery', {'id': self.key})

        problems_info = OrderedDict()
        for problem_set in scoreboard_data['data']['contest']['ordered_problem_sets']:
            for problem in problem_set['ordered_problems_with_display_indices']:
                code = str(problem['problem']['id'])
                info = {
                    'short': problem['display_index'],
                    'code': code,
                    'name': problem['problem']['problem_title'],
                    'full_score': problem['problem']['point_value'],
                    'url': self.url.rstrip('/') + '/problems/' + problem['display_index'],
                }
                problems_info[info['code']] = info

        limit = 1000
        total = scoreboard_data['data']['contest']['entrant_performance_summaries']['count']

        result = OrderedDict()
        for page in tqdm.trange((total + limit - 1) // limit, desc='paging'):
            data = query('CCEScoreboardQuery', {
                'id': self.key,
                'start': page * limit,
                'count': limit,
                'friends_only': False,
                'force_limited_data': False,
            })

            for row in data['data']['contest']['entrant_performance_summaries']['nodes']:
                row.update(row.pop('entrant'))
                handle = row.pop('id')
                r = result.setdefault(handle, OrderedDict())
                r['member'] = handle

                r['name'] = row.pop('display_name')
                r['solving'] = row.pop('total_score')
                r['place'] = row.pop('rank')

                penalty = row.pop('total_penalty')
                if penalty:
                    r['penalty'] = self.to_time(penalty)

                problems = r.setdefault('problems', {})
                solved = 0
                for problem in row.pop('problems'):
                    code = str(problem['problem']['id'])
                    problem = problem['representative_submission']
                    verdict = problem['submission_overall_result'].lower()
                    p = problems.setdefault(problems_info[code]['short'], {})
                    if verdict == 'accepted':
                        p['result'] = '+'
                        p['binary'] = True
                        solved += 1
                    else:
                        p['result'] = '-'
                        p['verdict'] = verdict
                        p['binary'] = False
                    p['time'] = self.to_time(problem['submission_time_after_contest_start'])
                    p['url'] = problem['submission_source_code_download_uri']
                    p['external_solution'] = True

                r['solved'] = {'solving': solved}

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }

        if re.search(r'\bfinals?\b', self.name, re.IGNORECASE):
            standings['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}

        return standings

    @staticmethod
    def get_source_code(contest, problem):
        solution = REQ.get(problem['url'])
        return {'solution': solution}


def run():
    from clist.models import Contest
    qs = Contest.objects.filter(resource__host__regex='facebook').order_by('start_time')

    contest = qs.first()
    print(contest.title, contest.start_time.year)
    statictic = Statistic(contest=contest)
    pprint(statictic.get_standings())
