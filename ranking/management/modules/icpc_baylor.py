#!/usr/bin/env python

import re
import json
from pprint import pprint
from collections import OrderedDict
from urllib.parse import urljoin
import html

from ranking.management.modules.common import REQ, BaseModule, parsed_table, FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @staticmethod
    def _json_load(data):
        try:
            ret = json.loads(data)
        except json.decoder.JSONDecodeError:
            data = re.sub(r"\\'", "'''", data)
            data = re.sub("'", '"', data)
            data = re.sub('"""', "'", data)
            ret = json.loads(data)
        return ret

    @staticmethod
    def _get_medals(year):
        default = OrderedDict([(k, 4) for k in ('gold', 'silver', 'bronze')])

        main_url = 'https://icpc.baylor.edu/'
        page = REQ.get(main_url)
        match = re.search('src="(?P<js>/static/js/main.[^"]*.js)"', page)
        if not match:
            return default
        js_url = match.group('js')

        page = REQ.get(js_url)
        match = re.search('XWIKI:"(?P<xwiki>[^"]*)"', page)
        if not match:
            return default
        xwiki_url = match.group('xwiki')
        xwiki_url = urljoin(main_url, xwiki_url).rstrip('/') + '/'

        medal_result_url = urljoin(xwiki_url, f'community/results-{year}')

        page = REQ.get(medal_result_url)
        json_data = json.loads(page)
        regex = '''<table[^>]*id=["']medalTable[^>]*>.*?</table>'''
        match = re.search(regex, json_data['content'], re.DOTALL)
        if not match:
            return default

        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)
        medals = OrderedDict()
        fields = ('gold', 'silver', 'bronze')
        for f in fields:
            medals[f] = 0
        for r in table:
            _, v = next(iter(r.items()))
            for attr in v.attrs.get('class', '').split():
                if attr in fields:
                    medals[attr] = medals.get(attr, 0) + 1
                    break
        if not medals:
            return default
        return medals

    def get_standings(self, users=None, statistics=None):
        year = self.start_time.year
        year = year + 1 if self.start_time.month >= 9 else year
        season = '%d-%d' % (year - 1, year)

        standings_urls = []
        if not self.standings_url:
            for url in (
                f'http://static.kattis.com/icpc/wf{year}/',
                f'https://zibada.guru/finals/{year}/',
                f'http://web.archive.org/web/{year}/https://icpc.baylor.edu/scoreboard/',
            ):
                try:
                    page = REQ.get(url)
                except FailOnGetResponse:
                    continue

                if 'web.archive.org' in REQ.last_url and f'/{year}' not in REQ.last_url:
                    continue

                standings_urls.append(url)
        else:
            standings_urls.append(self.standings_url)

        if not standings_urls:
            raise ExceptionParseStandings(f'Not found standings url year = {year}')

        for standings_url in standings_urls:
            page = REQ.get(standings_url)

            result = {}
            problems_info = OrderedDict()
            has_submission = False

            if 'zibada' in standings_url:
                match = re.search(r' = (?P<data>[\{\[].*?);?\s*$', page, re.MULTILINE)
                if match:
                    names = self._json_load(match.group('data'))
                else:
                    names = None

                try:
                    page = REQ.get('standings.js')
                    match = re.search(r' = (?P<data>\{.*?);?\s*$', page, re.MULTILINE)
                    data = self._json_load(match.group('data'))
                except Exception:
                    assert names
                    data = names

                for p_name in data['problems']:
                    problems_info[p_name] = {'short': p_name}

                events = data.pop('events', None)
                if events:
                    teams = {}
                    time_divider = 60
                    events.sort(key=lambda e: int(e.split()[-1]))
                    for e in events:
                        tid, p_name, status, attempt, time = e.split()
                        time = int(time)

                        team = teams.setdefault(tid, {})
                        problems = team.setdefault('problems', {})
                        result = problems.get(p_name, {}).get('result', '')
                        if not result.startswith('?') and status.startswith('?'):
                            continue
                        has_submission = True
                        if status == '+':
                            attempt = int(attempt) - 1
                            p_info = problems_info[p_name]
                        problems[p_name] = {
                            'time': time,
                            'result': '+' if status == '+' and attempt == 0 else f'{status}{attempt}',
                        }
                    for tid, team in teams.items():
                        name = names[int(tid)][0]
                        name = html.unescape(name)
                        team['member'] = f'{name} {season}'
                        team['name'] = name
                        penalty = 0
                        solving = 0
                        for p_name, problem in team.get('problems', {}).items():
                            if problem['result'].startswith('+'):
                                solving += 1
                                attempt_penalty = (int(problem['result'].lstrip('+') or 0)) * 20 * time_divider
                                penalty += problem['time'] + attempt_penalty
                        team['penalty'] = int(round(penalty / time_divider))
                        team['solving'] = solving
                else:
                    teams = {}
                    time_divider = 1
                    data_teams = data['teams']
                    if isinstance(data_teams, dict):
                        data_teams = data_teams.values()
                    for team in data_teams:
                        row = {}

                        def get(key, index):
                            return team[key] if isinstance(team, dict) else team[index]

                        name = get('name', 0)
                        name = html.unescape(name)
                        row['member'] = f'{name} {season}'
                        row['name'] = name
                        row['solving'] = int(get('score', 2))
                        row['penalty'] = int(get('time', 3))

                        if isinstance(team, dict):
                            team['problems'] = [team[str(index)] for index in range(len(data['problems']))]

                        problems = row.setdefault('problems', {})
                        for p_name, verdict in zip(data['problems'], get('problems', 4)):
                            if not verdict:
                                continue
                            if isinstance(verdict, dict):
                                verdict = {k[0]: v for k, v in verdict.items()}
                                verdict['a'] = int(verdict['a'])
                                if isinstance(verdict.get('p'), int):
                                    verdict['a'] += verdict['p']
                                if isinstance(verdict['s'], str):
                                    verdict['s'] = int(verdict['s'])
                                status = '+' if verdict['s'] else ('?' if verdict.get('p', False) else '-')
                                time = verdict['t']
                                result = verdict['a']
                                time_divider = 1000 * 60
                                if not result:
                                    continue
                            else:
                                status, result = verdict.split(' ', 1)
                                if ' ' in result:
                                    result, time = result.split()
                                    time = int(time)
                                else:
                                    time = None
                                result = int(result)
                            has_submission = True
                            problem = problems.setdefault(p_name, {})
                            if status == '+':
                                problem['time'] = time
                                problem['result'] = '+' if result == 1 else f'+{result - 1}'
                            else:
                                problem['result'] = f'{status}{result}'
                        teams[row['member']] = row

                teams = list(teams.values())
                teams.sort(key=lambda t: (t['solving'], -t['penalty']), reverse=True)
                rank = 0
                prev = None
                for i, t in enumerate(teams):
                    curr = (t['solving'], t['penalty'])
                    if prev != curr:
                        rank = i + 1
                        prev = curr
                    t['place'] = rank
                result = {t['member']: t for t in teams}

                problems_info = OrderedDict(sorted(problems_info.items()))
            else:
                regex = '''<table[^>]*(?:id=["']standings|class=["']scoreboard)[^>]*>.*?</table>'''
                match = re.search(regex, page, re.DOTALL)
                html_table = match.group(0)

                table = parsed_table.ParsedTable(html_table)
                time_divider = 1
                for r in table:
                    row = {}
                    problems = row.setdefault('problems', {})
                    for k, vs in r.items():
                        if isinstance(vs, list):
                            v = ' '.join(i.value for i in vs if i.value)
                        else:
                            v = vs.value
                        k = k.lower().strip('.')
                        v = v.strip()
                        if k in ('rank', 'rk'):
                            row['place'] = v
                        elif k == 'team':
                            row['member'] = f'{v} {season}'
                            row['name'] = v
                        elif k == 'time':
                            row['penalty'] = int(v)
                        elif k == 'slv':
                            row['solving'] = int(v)
                        elif k == 'score':
                            if ' ' in v:
                                row['solving'], row['penalty'] = map(int, v.split())
                            else:
                                row['solving'] = int(v)
                        elif len(k) == 1:
                            k = k.title()
                            if k not in problems_info:
                                problems_info[k] = {'short': k}
                                if 'title' in vs.header.attrs:
                                    problems_info[k]['name'] = vs.header.attrs['title']

                            v = re.sub(r'([0-9]+)\s+([0-9]+)\s+tr.*', r'\2 \1', v)
                            v = re.sub('tr[a-z]*', '', v)
                            v = re.sub('-*', '', v)
                            v = v.strip()
                            if not v:
                                continue

                            has_submission = True

                            p = problems.setdefault(k, {})
                            if ' ' in v:
                                pnt, time = map(int, v.split())
                                p['result'] = '+' if pnt == 1 else f'+{pnt - 1}'
                                p['time'] = time

                                if (
                                    'solvedfirst' in vs.column.attrs.get('class', '')
                                    or vs.column.node.xpath('.//*[contains(@class, "score_first")]')
                                ):
                                    p['first_ac'] = True
                            else:
                                p['result'] = f'-{v}'
                    result[row['member']] = row

            if not has_submission:
                continue

            first_ac_of_all = None
            for team in result.values():
                for p_name, problem in team['problems'].items():
                    p_info = problems_info[p_name]
                    if not problem['result'].startswith('+'):
                        continue
                    time = problem['time']
                    if 'first_ac' not in p_info or time < p_info['first_ac']:
                        p_info['first_ac'] = time
                    if first_ac_of_all is None or time < first_ac_of_all:
                        first_ac_of_all = time
                    if problem.get('first_ac'):
                        p_info['has_first_ac'] = True

            for team in result.values():
                for p_name, problem in team['problems'].items():
                    p_info = problems_info[p_name]
                    if problem['result'].startswith('+'):
                        if p_info.get('has_first_ac') and not problem.get('first_ac'):
                            continue
                        if problem['time'] == p_info['first_ac']:
                            problem['first_ac'] = True
                        if problem['time'] == first_ac_of_all:
                            problem['first_ac_of_all'] = True
                    if 'time' in problem:
                        problem['time'] = int(round(problem['time'] / time_divider))

            without_medals = any(
                p['result'].startswith('?')
                for row in result.values()
                for p in row.get('problems', {}).values()
            )

            options = {'per_page': None}
            if not without_medals:
                medals = self._get_medals(year)
                medals = [{'name': k, 'count': v} for k, v in medals.items()]
                options['medals'] = medals

            standings = {
                'result': result,
                'url': standings_url,
                'problems': list(problems_info.values()),
                'options': options,
            }
            return standings

        raise ExceptionParseStandings(f'Not found standings url from {standings_urls}')


if __name__ == "__main__":
    from datetime import datetime
    statictic = Statistic(
        name='ACM-ICPC World Finals. China',
        standings_url=None,
        key='ACM-ICPC World Finals. China 2008',
        start_time=datetime.strptime('2008-04-02', '%Y-%m-%d'),
    )
    pprint(statictic.get_standings())
