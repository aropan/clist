# -*- coding: utf-8 -*-

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from urllib.parse import unquote

import tqdm
from dateutil import parser

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    COMPETITION_INFO_API_URL_ = 'https://www.bubblecup.org/_api/competitionInfo'
    ROUND_INFO_API_URL_ = 'https://www.bubblecup.org/_api/ResultsRoundInfo'
    SOLVED_BY_API_URL_ = 'https://www.bubblecup.org/_api/SolvedBy?id={code}'
    PROBLEM_API_URL_ = 'https://www.bubblecup.org/_api/Problems/View/{code}'
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

        default_problems_info = OrderedDict([
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
                for p in default_problems_info.values():
                    p['full_score'] = level
        d_problems_info = OrderedDict()

        result = dict()

        has_scoring = {}
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
            problems_info = d_problems_info.setdefault(division, deepcopy(default_problems_info))

            participaty_type = {
                'Team': 'Team',
                'individual': 'Competitor',
            }[ctype]

            sorted_data = sorted(data['standings'], key=lambda r: r['score'], reverse=True)
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
                    for m in matches:
                        k = m['code']
                        if k not in problems_info:
                            continue
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
                    pbar.update()

            if max_points_challenge_problem is not None:
                for code, problem_info in problems_info.items():
                    key = problem_info['short']
                    target = self.info.get('parse', {}).get('problems', {}).get(key, {}).get('target')

                    if target is None:
                        url = self.PROBLEM_API_URL_.format(**problem_info)
                        if url not in has_scoring:
                            page = REQ.get(url)
                            data = json.loads(page)
                            has_scoring[url] = bool(re.search(r'####\s*Scoring:\s+', data['statement']))
                        if has_scoring[url]:
                            for r in division_result.values():
                                p = r['problems'].get(key, {})
                                if 'result' not in p:
                                    continue
                                p['status'] = p.pop('result')
                        continue

                    problem_info['full_score'] = max_points_challenge_problem

                    if target == 'minimize':
                        func = min
                    elif target == 'maximize':
                        func = max
                    else:
                        raise ExceptionParseStandings(f'unknown target = {target}')

                    opt = None
                    for r in division_result.values():
                        res = r['problems'].get(key, {}).get('result')
                        if res is None:
                            continue
                        res = float(res)
                        if opt is None:
                            opt = res
                        else:
                            opt = func(opt, res)

                    for r in division_result.values():
                        p = r['problems'].get(key, {})
                        if 'result' not in p:
                            continue
                        p['status'] = p['result']
                        if opt is None or abs(opt) < 1e-9:
                            p.pop('result')
                            continue
                        if target == 'minimize':
                            coefficient = 1 - (1 - opt / float(p['result'])) ** .5
                        elif target == 'maximize':
                            coefficient = 1 - (1 - float(p['result']) / opt) ** .5
                        if coefficient < 1:
                            p['partial'] = True
                        p['result'] = round(max_points_challenge_problem * coefficient, 2)

            for r in division_result.values():
                solved = 0
                for p in r['problems'].values():
                    if not p.get('partial') and 'result' in p and float(p['result']) > 0:
                        solved += 1
                r['solved'] = {'solving': solved}

            result.update(division_result)

        standings_url = self.STANDING_URL_.format(cid=round_infos['teamCompetitionPremierLeagueId'])

        problem_info = {'division': OrderedDict(((d, list(ps.values())) for d, ps in d_problems_info.items()))}

        if len(problem_info['division']) == 1:
            problems_info = next(iter(problem_info['division'].values()))

        standings = {
            'result': result,
            'url': standings_url,
            'problems': problem_info,
            'divisions_order': divisions_order,
            'hidden_fields': ['full_name', 'school', 'city', 'birth_year'],
        }
        return standings
