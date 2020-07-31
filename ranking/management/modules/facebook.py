#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
import tqdm
from pprint import pprint
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

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
                headers={'accept-language': 'en-US,en;q=1.0'}
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
        if users or users is None:
            has_users_filter = bool(users)
            users = set(users) if users else None
            with PoolExecutor(max_workers=3) as executor:
                stop = False

                def fetch_page(page):
                    if stop:
                        return
                    data = query('CCEScoreboardQuery', {
                        'id': self.key,
                        'start': page * limit,
                        'count': limit,
                        'friends_only': False,
                        'force_limited_data': False,
                    })
                    return data

                n_page = (total + limit - 1) // limit
                for data in tqdm.tqdm(executor.map(fetch_page, range(n_page)), total=n_page, desc='paging'):
                    if not data:
                        continue

                    for row in data['data']['contest']['entrant_performance_summaries']['nodes']:
                        row.update(row.pop('entrant'))
                        handle = row.pop('id')
                        if has_users_filter and handle not in users:
                            continue

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
                            input_download_status = problem.get('input_download_status', '')
                            problem = problem['representative_submission'] or {}
                            verdict = problem.get('submission_overall_result', input_download_status).lower()
                            p = problems.setdefault(problems_info[code]['short'], {})
                            if verdict == 'accepted':
                                p['result'] = '+'
                                p['binary'] = True
                                solved += 1
                            elif verdict == 'hidden':
                                p['result'] = '?'
                                p['icon'] = '<i class="fas fa-question"></i>'
                            else:
                                if 'submission_overall_result' not in problem:
                                    p['icon'] = '<i class="fas fa-hourglass-half"></i>'
                                p['binary'] = False
                                p['result'] = '-'
                                if verdict:
                                    p['verdict'] = verdict

                            if problem:
                                p['time'] = self.to_time(problem['submission_time_after_contest_start'])
                                url = problem['submission_source_code_download_uri']
                                if url:
                                    p['url'] = url
                                    p['external_solution'] = True

                        r['solved'] = {'solving': solved}

                        if has_users_filter:
                            users.remove(handle)
                            if not users:
                                stop = True
                                break

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
