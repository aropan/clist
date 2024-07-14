#!/usr/bin/env python3

from urllib.parse import urljoin

from clist.templatetags.extras import get_item, normalize_field
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings
from utils.timetools import now, parse_datetime


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = '/seasons/{season}/tracks/{track}/rating'
    API_STANDINGS_URL_FORMAT_ = '/api/seasons/{season}/tracks/{track}/leaderboard?currentPage={{page}}&pageSize={{page_size}}'  # noqa
    PROBLEM_URL_FORMAT_ = '/seasons/{season}/tracks/{track}/problem/{problem}'
    API_PROBLEM_URL_FORMAT_ = '/api/seasons/{season}/tracks/{track}/problem/search?currentPage={{page}}&pageSize={{page_size}}'  # noqa

    def get_standings(self, users=None, statistics=None):
        season = get_item(self, 'info.parse.slug')
        if not season:
            raise ExceptionParseStandings('Not found season')

        track = get_item(self, 'info.parse.track.slug')
        if not track:
            raise ExceptionParseStandings('Not found track')

        standings_url = self.STANDING_URL_FORMAT_.format(season=season, track=track)
        standings_url = urljoin(self.host, standings_url)

        def get_problems():
            api_problem_url = self.API_PROBLEM_URL_FORMAT_.format(season=season, track=track)
            api_problem_url = urljoin(self.host, api_problem_url)
            page = 1
            page_size = 100
            total_pages = None
            problems = []
            problems_scores = get_item(self, 'info.parse.problemScores')
            while total_pages is None or page <= total_pages:
                url = api_problem_url.format(page=page, page_size=page_size)
                data = REQ.get(url, return_json=True)
                data = data['result']
                for row in data['data']:
                    problem_url = self.PROBLEM_URL_FORMAT_.format(season=season, track=track, problem=row['slug'])
                    problem_url = urljoin(self.host, problem_url)
                    tags = row.pop('tags') or []
                    tags.extend(row.pop('groupSlugs') or [])
                    if row.pop('isChallenge', None):
                        tags.append('challenge')
                    problem = {
                        'url': problem_url,
                        'code': row.pop('id'),
                        'name': row.pop('title'),
                        'slug': row.pop('slug'),
                        'tags': tags,
                        'skip_in_standings': True,
                    }

                    for k, v in row.items():
                        k = normalize_field(k)
                        if k in {'solution_state'}:
                            continue
                        if k not in problem:
                            problem[k] = v

                    if 'starting_at' in problem and 'status' not in problem:
                        if problem['starting_at'] is None or now() > parse_datetime(problem['starting_at']):
                            problem['status'] = 'opened'
                        else:
                            problem['status'] = 'closed'

                    if problem.get('status') == 'closed':
                        full_score = 0
                    else:
                        full_score = problem.get('current_rate')
                    if full_score is not None:
                        problem['full_score'] = full_score
                        if full_score and problems_scores and problem['difficulty'] in problems_scores:
                            problem['relative_difficulty'] = full_score / problems_scores[problem['difficulty']]

                    problems.append(problem)
                total_pages = (data['total'] - 1) // page_size + 1
                page += 1
            return problems

        def get_result():
            api_standings_url = self.API_STANDINGS_URL_FORMAT_.format(season=season, track=track)
            api_standings_url = urljoin(self.host, api_standings_url)

            result = {}
            page = 1
            page_size = 100
            total_pages = None
            while total_pages is None or page <= total_pages:
                url = api_standings_url.format(page=page, page_size=page_size)
                data = REQ.get(url, return_json=True)
                data = data['result']
                for row in data['rows']:
                    penalty = row.pop('acceptedAt')
                    if not penalty:
                        continue
                    member = row.pop('nickname')
                    r = result.setdefault(member, {'member': member})
                    r['place'] = row.pop('place')
                    r['solving'] = row.pop('score')
                    r['penalty'] = parse_datetime(penalty).timestamp()

                    solved = row.pop('solvedProblems')
                    r['solved_problems'] = solved
                    r['solved'] = {'solving': solved}

                total_pages = (data['totalSize'] - 1) // page_size + 1
                page += 1
            return result

        problems_infos = get_problems()
        result = get_result()

        fields_types = {'penalty': ['timestamp']}

        standings = {
            'result': result,
            'url': standings_url,
            'fields_types': fields_types,
            'problems': problems_infos,
        }

        return standings
