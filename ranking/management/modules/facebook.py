#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime
from pprint import pprint

import pytz
import tqdm

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    API_GRAPH_URL_ = 'https://www.facebook.com/api/graphql/'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        REQ.get('https://facebook.com/')
        form = REQ.form(action='/login/')
        if form:
            data = {
                'email': conf.FACEBOOK_USERNAME,
                'pass': conf.FACEBOOK_PASSWORD,
            }
            REQ.submit_form(data=data, form=form)
            form = REQ.form(action='/login/')
            if form and 'validate-password' in form['url']:
                REQ.submit_form(data=data, form=form)

    def get_standings(self, users=None, statistics=None):
        page = REQ.get(self.standings_url)
        matches = re.finditer(r'\["(?P<name>[^"]*)",\[\],{"token":"(?P<token>[^"]*)"', page)
        tokens = {}
        for match in matches:
            tokens[match.group('name').lower()] = match.group('token')

        def query(name, variables):
            params = {
                'fb_dtsg': tokens.get('dtsginitialdata', ''),
                'lsd': tokens['lsd'],
                'fb_api_caller_class': 'RelayModern',
                'fb_api_req_friendly_name': name,
                'variables': json.dumps(variables),
                'doc_id': self.info['_scoreboard_ids'][name],
            }
            ret = REQ.get(
                self.API_GRAPH_URL_,
                post=params,
                headers={'accept-language': 'en-US,en;q=1.0'}
            )
            try:
                return json.loads(ret)
            except Exception as e:
                raise ExceptionParseStandings(f'Error on query {name} = {e}')

        variables = {'id': self.key, 'force_limited_data': False, 'show_all_submissions': False}
        scoreboard_data = query('CodingCompetitionsContestScoreboardQuery', variables)

        def get_advance():
            advancement = scoreboard_data['data']['contest'].get('advancement_requirement_text')

            if not advancement:
                return {}

            match = re.search('top (?P<place>[0-9]+) contestants', advancement)
            if match:
                return {'filter': [{'threshold': int(match.group('place')), 'operator': 'le', 'field': 'place'}]}

            match = re.search('least (?P<score>[0-9]+) points', advancement)
            if match:
                return {'filter': [{'threshold': int(match.group('score')), 'operator': 'ge', 'field': 'solving'}]}

            match = re.search('least (?P<count>[0-9]+) problem', advancement)
            if match:
                return {'filter': [{'threshold': int(match.group('count')), 'operator': 'ge', 'field': '_n_solved'}]}

            return {}

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

        has_hidden = False
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

                        country = row.pop('country_code_of_representation')
                        if country:
                            r['country'] = country

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
                                has_hidden = True
                            elif verdict == 'download_valid':
                                p['result'] = '?!'
                                p['icon'] = '<i class="fas fa-arrow-circle-down"></i>'
                                has_hidden = True
                            else:
                                if 'submission_overall_result' not in problem:
                                    p['icon'] = '<i class="fas fa-hourglass-half"></i>'
                                p['binary'] = False
                                p['result'] = '-'
                                if verdict:
                                    p['verdict'] = verdict

                            if problem:
                                p['time_in_seconds'] = problem['submission_time_after_contest_start']
                                p['time'] = self.to_time(problem['submission_time_after_contest_start'])
                                url = problem['submission_source_code_download_uri']
                                if url:
                                    p['url'] = url
                                    p['external_solution'] = True

                        r['solved'] = {'solving': solved}
                        r['_n_solved'] = solved

                        profile_picture = row
                        for field in ('entrant_personal_info', 'individual_entrant_user', 'profile_picture', 'uri'):
                            profile_picture = profile_picture.get(field) or {}
                        r['info'] = {'download_avatar_url_': profile_picture if profile_picture else None}

                        if has_users_filter:
                            users.remove(handle)
                            if not users:
                                stop = True
                                break

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
            'advance': get_advance(),
        }

        if re.search(r'\bfinals?\b', self.name, re.IGNORECASE):
            if has_hidden or datetime.utcnow().replace(tzinfo=pytz.utc) < self.end_time:
                standings['options'] = {'medals': []}
            else:
                standings['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}

        return standings

    @staticmethod
    def get_source_code(contest, problem):
        solution = REQ.get(problem['url'], headers={'referer': 'https://www.facebook.com/'})
        return {'solution': solution}


def run():
    from clist.models import Contest
    qs = Contest.objects.filter(resource__host__regex='facebook').order_by('start_time')

    contest = qs.first()
    print(contest.title, contest.start_time.year)
    statictic = Statistic(contest=contest)
    pprint(statictic.get_standings())
