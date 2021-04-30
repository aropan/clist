# -*- coding: utf-8 -*-

import collections
import json
import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import unquote

import tqdm
from dateutil import parser

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    COMPETITION_INFO_API_URL_ = 'https://www.bubblecup.org/_api/competitionInfo'
    ROUND_INFO_API_URL_ = 'https://www.bubblecup.org/_api/ResultsRoundInfo'
    SOLVED_BY_API_URL_ = 'https://www.bubblecup.org/_api/SolvedBy?id={code}'
    RESULTS_API_URL_ = 'https://www.bubblecup.org/_api/ResultsSelectedResults/{cid}/{url}/{ctype}'
    TEAM_RESULTS_URL_ = 'https://www.bubblecup.org/CompetitorsCorner/{name}Results/{cid}/{uid}'
    PROBLEM_URL_ = 'https://www.bubblecup.org/CompetitorsCorner/Problem/{code}'
    STANDING_URL_ = 'https://www.bubblecup.org/CompetitorsCorner/Results/{cid}/Overall/Team'

    def get_standings(self, users=None, statistics=None):
        page = REQ.get(self.COMPETITION_INFO_API_URL_)
        data = json.loads(page)
        for round_data in data['rounds']:
            match = re.search(r'start\s*date\s*(?:<b[^>]*>)?(?P<start_time>[^<]*)(?:</b>)?.*end\s*date',
                              round_data['description'],
                              re.IGNORECASE)
            start_time = parser.parse(match.group('start_time'), tzinfos={'CET': 'UTC+1'})
            title = re.sub(r'\s+', ' ', round_data['name'])
            if start_time == self.start_time and title == self.name:
                break
        else:
            raise ExceptionParseStandings('not found round')

        m = re.search('maxPointsForProblem=(?P<score>[0-9]+)', round_data['description'])
        max_points_challenge_problem = int(m.group('score')) if m else None

        page = REQ.get(self.ROUND_INFO_API_URL_)
        round_infos = json.loads(page)
        for round_info in round_infos['roundDisplayInfo']:
            title = re.sub(r'\s+', ' ', round_info['displayName'])
            if title == self.name:
                break
        else:
            raise ExceptionParseStandings('not found round')

        problems_info = collections.OrderedDict([
            (p['code'], {
                'code': p['code'],
                'short': chr(i + ord('A')),
                'name': p['name'],
                'url': self.PROBLEM_URL_.format(**p),
            })
            for i, p in enumerate(round_data['problems'])
        ])
        if self.name.startswith('Round'):
            level = int(self.name.split()[-1])
            if level in [1, 2]:
                for p in problems_info.values():
                    p['full_score'] = level

        result = dict()

        divisions_order = []
        for cid, ctype in (
            (round_infos['teamCompetitionPremierLeagueId'], 'Team'),
            (round_infos['teamCompetitionRisingStarsId'], 'Team'),
            (round_infos['teamCompetitionPremierLeagueId'], 'individual'),
        ):
            url = self.RESULTS_API_URL_.format(cid=cid, url=round_info['url'],  ctype=ctype)
            page = REQ.get(url)
            data = json.loads(page)

            division = data['displayedName'].replace(self.name, '').strip().lower()
            if division not in divisions_order:
                divisions_order.append(division)

            participaty_type = {
                'Team': 'Team',
                'individual': 'Competitor',
            }[ctype]

            sorted_data = sorted(data['standings'], key=lambda r: r['score'], reverse=True)
            max_points = collections.defaultdict(int)
            division_result = dict()

            with PoolExecutor(max_workers=20) as executor, tqdm.tqdm(total=len(sorted_data)) as pbar:

                def fetch_team_results(d):
                    member = str(d['id'])
                    url = self.TEAM_RESULTS_URL_.format(cid=cid, uid=member, name=participaty_type)
                    page = REQ.get(url)

                    matches = re.finditer(
                        r'<a[^>]*href="[^"]*/Problem/(?P<code>[^"/]*)">[^<]*(?:\s*<[^>]*>)*(?P<score>[.0-9]+)',
                        page,
                    )
                    problems = {}
                    points = {}
                    for m in matches:
                        k = m['code']
                        if k not in problems_info:
                            continue
                        points[k] = m['score']
                        p = problems.setdefault(problems_info[k]['short'], {})
                        p['result'] = m['score']

                    matches = re.finditer(
                        '<a[^>]*href="[^"]*/CompetitorResults/[^"]*/(?P<account>[0-9]+)/?">(?P<name>[^<]*)</a>',
                        page,
                    )
                    users = [m.groupdict() for m in matches]

                    info = {
                        'problems': problems,
                        'url': url,
                        'member': member,
                        'points': points,
                    }

                    matches = re.finditer(
                        r'<tr[^>]*>\s*<td[^>]*><b>(?P<key>[^<]*)</b></td>\s*<td[^>]*>(?P<value>[^<]*)</td>\s*</tr>',
                        page,
                    )

                    more_info = {}
                    for m in matches:
                        k = m.group('key').lower().replace(' ', '_')
                        v = m.group('value')
                        if not v:
                            continue
                        more_info[k] = v
                    if more_info.get('name') and more_info.get('surname'):
                        info['full_name'] = '{name} {surname}'.format(**more_info)
                    if more_info.get('birth_year') == '0':
                        more_info.pop('birth_year')
                    for k in 'school', 'city', 'birth_year':
                        if more_info.get(k):
                            info[k] = more_info[k]

                    return d, info, users

                place = None
                last = None
                for index, (r, row, users) in enumerate(executor.map(fetch_team_results, sorted_data), start=1):
                    if last is None or abs(r['score'] - last) > 1e-7:
                        place = index
                        last = r['score']

                    row['name'] = r['name']
                    if users:
                        row['_members'] = users
                    row['place'] = place
                    row['solving'] = r['score']

                    country = unquote(r['country'])
                    country = re.sub(r'\s*\(.*$', '', country)
                    row['country'] = country

                    row['division'] = division
                    if ctype == 'individual':
                        row['_skip_for_problem_stat'] = True

                    division_result[row['member']] = row

                    for k, s in row.pop('points', {}).items():
                        max_points[k] = max(max_points[k], float(s))

                    pbar.update()

            if max_points_challenge_problem is not None:
                for code, value in max_points.items():
                    if code != round_data['problems'][-1]['code'] and value <= 2:
                        continue

                    problems_info[code]['full_score'] = max_points_challenge_problem

                    for r in division_result.values():
                        k = problems_info[code]['short']
                        if k in r['problems']:
                            p = r['problems'][k]
                            p['status'] = p['result']
                            k = 1 - (1 - float(p['result']) / value) ** .5
                            if k < 1:
                                p['partial'] = True
                            p['result'] = round(max_points_challenge_problem * k, 2)

            for r in division_result.values():
                solved = 0
                for p in r['problems'].values():
                    if not p.get('partial') and float(p['result']) > 0:
                        solved += 1
                r['solved'] = {'solving': solved}

            result.update(division_result)

        standings_url = self.STANDING_URL_.format(cid=round_infos['teamCompetitionPremierLeagueId'])

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
            'divisions_order': divisions_order,
            'hidden_fields': ['full_name', 'school', 'city', 'birth_year'],
        }
        return standings
