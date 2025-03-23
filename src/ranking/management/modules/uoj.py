# -*- coding: utf-8 -*-

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

import yaml
from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number, get_item
from ranking.management.modules.common import LOG, REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from utils.strings import strip_tags


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = self.standings_url or self.url.rstrip('/') + '/standings'

        page = REQ.get(standings_url)
        entries = re.findall(r'^([a-z_]+)\s*=\s*(.*);\s*$', page, flags=re.MULTILINE)
        variables = {k: yaml.safe_load(v) for k, v in entries}
        variables.pop('myname', None)
        variables.pop('contest_id', None)

        for key in ('contest_rule', 'standings', 'score', 'problems'):
            if key not in variables:
                raise ExceptionParseStandings(f'Not found "{key}" in variables')

        standings = variables.pop('standings')
        scorings = variables.pop('score')
        base_url = 'https://uoj.ac/'

        def fetch_problem(problem: tuple[int, int]):
            short, problem_id = problem
            problem_id = str(problem_id)
            problem_info = {'short': short, 'code': problem_id}
            for url in (
                urljoin(standings_url.rstrip('/'), f'problem/{problem_id}'),
                urljoin(base_url, f'/problem/{problem_id}'),
            ):
                try:
                    problem_page, response_code = REQ.get(url, return_code=True, ignore_codes={404})
                    if response_code == 404:
                        continue
                    problem_info['url'] = url
                    prefix = rf'(?:#\s*{problem_info["code"]}|{problem_info["short"]})'
                    name = re.search(rf'<h1[^>]*>\s*{prefix}.(.*?)</h1>', problem_page, re.DOTALL).group(1)
                    name = html.unescape(name).strip()
                    name = strip_tags(name)
                    problem_info['name'] = name
                    break
                except FailOnGetResponse as e:
                    LOG.warn(f'Fail to get problem names: {e}')
            return problem_info

        problems_infos = []
        with PoolExecutor(max_workers=8) as executor:
            problems_id = variables.pop('problems')
            problems_short = [chr(ord('A') + idx) for idx in range(len(problems_id))]
            problems_data = zip(problems_short, problems_id)
            for problem_info in executor.map(fetch_problem, problems_data):
                problems_infos.append(problem_info)

        result = {}
        for standings_row in standings:
            solving, penalty, (handle, rating, *addition_info), rank = standings_row

            scoring = scorings[handle]
            if not scoring:
                continue

            row = {
                'member': handle,
                'place': rank,
                'solving': solving,
                'penalty': self.to_time(penalty, num=3),
                'rating': rating,
            }

            if addition_info:
                addition_info = addition_info[0]
                row['name'] = addition_info.pop('team_name')
                info = row.setdefault('info', addition_info)
                info['is_team'] = True
                row.pop('rating')

            statistics_problems = get_item(statistics or {}, (handle, 'problems'), {})
            problems = row.setdefault('problems', statistics_problems)
            scoring = scoring.items() if isinstance(scoring, dict) else enumerate(scoring)
            for k, scoring_value in scoring:
                score, time, submission_id, *scoring_value = map(int, scoring_value)
                short = problems_infos[int(k)]['short']
                problem = problems.setdefault(short, {})
                problem['result'] = as_number(score)
                if scoring_value:
                    _, n_attempts, _ = scoring_value
                    problem['penalty'] = n_attempts
                    if time > 0:
                        time -= 1200 * n_attempts
                if time > 0:
                    problem['time'] = self.to_time(time, num=3)
                    problem['time_in_seconds'] = time
                if submission_id > 0:
                    problem['submission_id'] = submission_id
                    problem['url'] = urljoin(standings_url, f'/submission/{submission_id}')
            result[handle] = row

        standings = {
            'result': result,
            'url': standings_url,
            'problems': problems_infos,
            'options': {'data': variables},
            'hidden_fields': ['rating'],
        }

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=2)
        def fetch_profile(handle):
            profile_url = resource.profile_url.format(account=handle)
            profile_page = REQ.get(profile_url, n_attempts=2)
            data = {}

            matches = re.finditer(
                r'''
                <h4[^>]*class="list-group-item-heading"[^>]*>(?P<filed>[^<]*)</h4>\s*
                <p[^>]*class="list-group-item-text"[^>]*>(?:<[^>]*>)?(?P<value>[^<]*)
                ''',
                profile_page,
                re.VERBOSE,
            )
            variables = {match.group('filed').strip(): match.group('value').strip() for match in matches}
            mapping = {'Rating': 'rating', 'Email': 'email', 'QQ': 'qq', 'Motto': 'motto', '格言': 'motto'}
            for key in set(mapping) & set(variables):
                field = mapping[key]
                value = variables[key]
                data[field] = value

            if match := re.search('<img[^>]*alt="[^"]*Avatar[^"]*"[^>]*src="(?P<avatar>[^"]*)"[^>]*>', profile_page):
                data['avatar_url'] = urljoin(profile_url, match.group('avatar'))

            match = re.search(r'rating_data\s*=\s*(?P<history>\[.*?\]);', profile_page)
            history = json.loads(match.group('history'))[0]

            return data, history

        with PoolExecutor(max_workers=8) as executor:
            profiles = executor.map(fetch_profile, users)
            for user, account, (data, history) in zip(users, accounts, profiles):
                if pbar:
                    pbar.update()

                contest_addition_update = {}
                last_rating = None
                for contest in history:
                    timestamp, rating, contest_key, _, rank, _, rating_change = contest
                    contest_key = str(contest_key)
                    update = contest_addition_update.setdefault(contest_key, {})
                    if (rating := as_number(rating, force=True)) is not None:
                        update['new_rating'] = rating
                        last_rating = rating
                    if (rating_change := as_number(rating_change, force=True)) is not None:
                        update['rating_change'] = rating_change
                    update['_rank'] = rank
                    update['_with_create'] = True
                if (rating := as_number(data.get('rating'), force=True)) is not None:
                    data['rating'] = rating
                elif last_rating is not None:
                    data['rating'] = last_rating
                else:
                    data.pop('rating', None)

                if account.info.get('is_team'):
                    data.pop('rating', None)
                    for update in contest_addition_update.values():
                        update.pop('new_rating', None)
                        update.pop('rating_change', None)

                yield {
                    'info': data,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': 'key',
                        'clear_rating_change': True,
                        'try_renaming_check': True,
                        'try_fill_missed_ranks': True,
                    }
                }
