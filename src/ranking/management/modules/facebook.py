#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from time import sleep

import pytz
import requests
import tqdm
from django.utils.timezone import now
from ratelimiter import RateLimiter

# from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


def is_rate_limit_error(e):
    return bool(re.search('rate limit exceeded', str(e), re.I))


class Statistic(BaseModule):
    API_GRAPH_URL_ = 'https://www.facebook.com/api/graphql/'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        with open('sharedfiles/resource/facebook/headers.json') as file:
            self.headers = json.load(file)

    def get_standings(self, users=None, statistics=None, **kwargs):
        n_proxies = 50
        req = REQ.duplicate(cookie_filename='sharedfiles/resource/facebook/cookies.txt')

        is_final = bool(re.search(r'\bfinals?\b', self.name, re.IGNORECASE))
        page = req.get(self.standings_url, headers=self.headers)
        matches = re.finditer(r'\["(?P<name>[^"]*)",\[\],{"token":"(?P<token>[^"]*)"', page)
        tokens = {}
        for match in matches:
            tokens[match.group('name').lower()] = match.group('token')

        req = req.with_proxy(
            time_limit=10,
            n_limit=n_proxies,
            filepath_proxies='sharedfiles/resource/facebook/proxies',
            attributes={'n_attempts': n_proxies},
        )
        lock = Lock()

        def query(name, variables):
            params = {
                'fb_dtsg': tokens.get('dtsginitialdata', ''),
                'lsd': tokens['lsd'],
                'fb_api_caller_class': 'RelayModern',
                'fb_api_req_friendly_name': name,
                'variables': json.dumps(variables),
                'server_timestamps': True,
                'doc_id': self.info['_scoreboard_ids'][name],
            }

            n_attempts = 1
            n_rate_limit_exceeded = 3
            seen = set()
            attempt = 0
            while True:
                attempt += 1

                ret = req.get(
                    self.API_GRAPH_URL_,
                    post=params,
                    headers={'Accept-Language': 'en-US,en;q=1.0', **self.headers},
                )
                try:
                    ret = json.loads(ret)
                    if 'errors' not in ret:
                        return ret
                    msg = f'Error on query {name}'
                    messages = []
                    for error in ret['errors']:
                        if isinstance(error, dict) and 'message' in error:
                            messages.append(error['message'])
                    if messages:
                        msg += f' = {messages}'
                except Exception as e:
                    msg = f'Exception on query {name} = {e}'

                if msg not in seen:
                    LOG.warning(msg)
                    seen.add(msg)

                if is_rate_limit_error(msg):
                    req.proxy_fail(force=True)
                if n_rate_limit_exceeded and is_rate_limit_error(msg):
                    n_rate_limit_exceeded -= 1
                elif n_attempts:
                    n_attempts -= 1
                else:
                    raise ExceptionParseStandings(msg)

                with lock:
                    sleep(attempt)

        variables = {'id': self.key, 'force_limited_data': False, 'show_all_submissions': False,
                     'should_include_scoreboard': True}
        scoreboard_data = query('CodingCompetitionsContestScoreboardQuery', variables)

        def get_advance():
            advancement = contest_data.get('advancement_requirement_text')
            if advancement:
                match = re.search('top (?P<place>[0-9]+) contestants', advancement)
                if match:
                    threshold = int(match.group('place'))
                    return {'filter': [{'threshold': threshold, 'operator': 'le', 'field': 'place'}]}

                match = re.search('least (?P<score>[0-9]+) points', advancement)
                if match:
                    threshold = int(match.group('score'))
                    return {'filter': [{'threshold': threshold, 'operator': 'ge', 'field': 'solving'}]}

                match = re.search('least (?P<count>[0-9]+) problem', advancement)
                if match:
                    threshold = int(match.group('count'))
                    return {'filter': [{'threshold': threshold, 'operator': 'ge', 'field': '_n_solved'}]}

            advancement = contest_data.get('advancement_mode')
            if advancement:
                threshold = contest_data['advancement_value']
                if advancement == 'RANK':
                    return {'filter': [{'threshold': threshold, 'operator': 'le', 'field': 'place'}]}
                if advancement == 'SCORE':
                    return {'filter': [{'threshold': threshold, 'operator': 'ge', 'field': 'solving'}]}
                if advancement == 'NUM_PROBLEMS_SOLVED':
                    return {'filter': [{'threshold': threshold, 'operator': 'ge', 'field': '_n_solved'}]}

            return {}

        def get_contest(scoreboard_data):
            data = scoreboard_data['data']
            for k in 'contest', 'fetch__CodingContest':
                if k in data:
                    return data[k]

        problems_info = OrderedDict()
        contest_data = get_contest(scoreboard_data)
        for problem_set in contest_data['ordered_problem_sets']:
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

        limit = 50
        total = contest_data['entrant_performance_summaries']['count']
        info_paging_offset = self.info.get('_paging_offset', 0) if statistics else 0
        paging_offset = info_paging_offset
        parsed_percentage = None

        has_hidden = False
        result = OrderedDict()
        if users or users is None:
            has_users_filter = bool(users)
            if has_users_filter:
                users = set(users)
                paging_offset = 0

            with PoolExecutor(max_workers=3) as executor:
                stop = False

                @RateLimiter(max_calls=1, period=1)
                def fetch_page(page):
                    if stop:
                        return
                    try:
                        data = query('CCEScoreboardQuery', {
                            'id': self.key,
                            'start': page * limit,
                            'count': limit,
                            'friends_only': False,
                            'force_limited_data': False,
                            'country_filter': None,
                            'show_all_submissions': False,
                            'substring_filter': '',
                        })
                    except Exception as e:
                        if not is_rate_limit_error(e):
                            LOG.error(f'Fetch page exception = {e}')
                        return
                    return data

                n_page = (total + limit - 1) // limit
                pages = list(range(paging_offset, n_page))
                tqdm_iterator = tqdm.tqdm(executor.map(fetch_page, pages), total=len(pages), desc='paging')
                process_pages = set()
                for page, data in zip(pages, tqdm_iterator):
                    if data is None:
                        stop = True
                        break
                    if not data:
                        continue
                    process_pages.add(page)
                    for row in get_contest(data)['entrant_performance_summaries']['nodes']:
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
                                p['result'] = '+?'
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

                        if not problems and not is_final:
                            result.pop(handle)
                            continue
                while paging_offset in process_pages:
                    paging_offset += 1
                parsed_percentage = paging_offset * 100. / n_page if n_page else None
                if paging_offset >= n_page:
                    paging_offset = 0

        req.__exit__()

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
            'advance': get_advance(),
            'has_hidden': has_hidden,
            'keep_results': info_paging_offset or paging_offset,
            'info_fields': ['_paging_offset'],
        }
        if not has_users_filter:
            standings['_paging_offset'] = paging_offset
            standings['parsed_percentage'] = parsed_percentage
            if (
                parsed_percentage and parsed_percentage < 100 and
                self.end_time < now() < self.end_time + timedelta(days=1)
            ):
                standings['timing_statistic_delta'] = timedelta(minutes=15)

        if is_final:
            standings['series'] = 'FHC'
            if has_hidden or datetime.utcnow().replace(tzinfo=pytz.utc) < self.end_time:
                standings['options'] = {'medals': []}
            else:
                standings['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}

        return standings

    @staticmethod
    def get_source_code(contest, problem):
        solution = requests.get(problem['url']).content.decode('utf8')
        return {'solution': solution}
