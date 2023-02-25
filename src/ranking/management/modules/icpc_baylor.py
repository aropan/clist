#!/usr/bin/env python

import html
import json
import logging
import re
import traceback
from collections import OrderedDict
from datetime import timedelta
from pprint import pprint
from urllib.parse import urljoin, urlparse

import coloredlogs
from django.utils.timezone import now
from lxml import etree

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


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

        def get_from_icpc(year):
            medal_result_url = f'https://icpc.global/api/help/cms/virtpublic/community/results-{year}'
            page = REQ.get(medal_result_url)
            try:
                json_data = json.loads(page)
            except json.decoder.JSONDecodeError:
                return
            regex = '''<table[^>]*id=["']medalTable[^>]*>.*?</table>'''
            match = re.search(regex, json_data['content'], re.DOTALL)
            if not match:
                return

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
                return
            return medals

        ret = get_from_icpc(year)
        return ret

    def get_standings(self, users=None, statistics=None):
        is_regional = getattr(self, 'is_regional', False)
        entry = re.search(r'\b[0-9]{4}\b-\b[0-9]{4}\b', self.key)
        if entry:
            season = entry.group(0)
            year = int(season.split('-')[-1])
        else:
            year = int(re.search(r'\b[0-9]{4}\b', self.key).group(0))
            season = '%d-%d' % (year - 1, year)

        icpc_standings_url = f'https://icpc.global/community/results-{year}'
        icpc_api_standings_url = f'https://icpc.global/api/help/cms/virtpublic/community/results-{year}'

        standings_urls = []
        if not self.standings_url:
            for url in (
                'https://icpc.global/scoreboard/',
                'https://pc2.ecs.baylor.edu/scoreboard/',
                f'http://static.kattis.com/icpc/wf{year}/',
                f'https://zibada.guru/finals/{year}/',
                f'http://web.archive.org/web/{year}/https://icpc.baylor.edu/scoreboard/',
                f'http://web.archive.org/web/{year}/https://icpc.global/scoreboard/',
                f'https://cphof.org/standings/icpc/{year}',
                icpc_api_standings_url,
            ):
                try:
                    page = REQ.get(url)
                except FailOnGetResponse:
                    continue

                if urlparse(REQ.last_url).hostname == 'web.archive.org' and f'/{year}' not in REQ.last_url:
                    continue

                if not re.search(rf'\b(world\s*finals\s*{year}|{year}\s*world\s*finals)\b', page, re.IGNORECASE):
                    continue

                standings_urls.append(url)
        else:
            if self.standings_url == icpc_standings_url:
                standings_urls.append(icpc_api_standings_url)
            else:
                standings_urls.append(self.standings_url)

        if not standings_urls:
            raise ExceptionParseStandings(f'Not found standings url year = {year}')

        for standings_url in standings_urls:
            if (
                not re.search(r'\b[0-9]{4}\b', standings_url)
                and now() - self.start_time > timedelta(days=30) and statistics
            ):
                continue

            is_icpc_api_standings_url = standings_url == icpc_api_standings_url
            page = REQ.get(standings_url)

            result = {}
            hidden_fields = set(self.info.get('hidden_fields', [])) | {'region'}
            problems_info = OrderedDict()

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
                        if not result.startswith('?') and status.startswith('?') or result.startswith('+'):
                            continue
                        if status == '+':
                            attempt = int(attempt) - 1
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
                if is_icpc_api_standings_url:
                    page = re.sub(r'</table>\s*<table>\s*(<tr[^>]*>\s*<t[^>]*>)', r'\1', page, flags=re.I)

                regex = '''(?:<table[^>]*(?:id=["']standings|class=["']scoreboard)[^>]*>|"content":"[^"]*<table[^>]*>|<table[^>]*class="[^"]*(?:table[^"]*){3}"[^>]*>).*?</table>'''  # noqa
                match = re.search(regex, page, re.DOTALL)
                if match:
                    html_table = match.group(0)
                    table = parsed_table.ParsedTable(html_table, with_not_full_row=is_icpc_api_standings_url)
                else:
                    table = []
                time_divider = 1
                last_place = None
                is_ineligible = False
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
                        if k in ('rank', 'rk', 'place'):
                            if not isinstance(vs, list):
                                medal = vs.column.node.xpath('.//img/@alt')
                                if medal and medal[0].endswith('medal'):
                                    row['medal'] = medal[0].split()[0]
                                for medal, ending in (('gold', '🥇'), ('silver', '🥈'), ('bronze', '🥉')):
                                    if v.endswith(ending):
                                        row['medal'] = medal
                                        v = v[:-len(ending)].strip()
                            row['place'] = v
                        elif k in ('team', 'name', 'university'):
                            if isinstance(vs, list):
                                for el in vs:
                                    images = el.column.node.xpath('.//img[@src]')
                                    if images:
                                        for img in images:
                                            src = img.attrib['src']
                                            if 'flags/' in src:
                                                row['country'] = img.attrib['title']
                                            else:
                                                logo = urljoin(standings_url, src)
                                                row.setdefault('info', {}).setdefault('logo', logo)
                                for el in vs:
                                    region = el.column.node.xpath('.//*[@class="badge badge-warning"]')
                                    if region:
                                        region = ''.join([s.strip() for s in region[0].xpath('text()')])
                                    if region:
                                        if is_regional:
                                            if region.lower() == 'ineligible':
                                                is_ineligible = True
                                        else:
                                            row['region'] = region
                                            if v.lower().startswith(region.lower()):
                                                v = v[len(region):].strip()
                            v = v.replace('\n', ' ')
                            if 'cphof' in standings_url:
                                member = vs.column.node.xpath('.//a/text()')[0].strip()
                                row['member'] = f'{member} {season}'
                            else:
                                row['member'] = f'{v} {season}'
                            row['name'] = v
                        elif k in ('time', 'penalty', 'total time (min)', 'minutes'):
                            if v and v != '?':
                                row['penalty'] = int(v)
                        elif k in ('slv', 'solved', '# solved'):
                            row['solving'] = int(v)
                        elif k == 'score':
                            if ' ' in v:
                                row['solving'], row['penalty'] = map(int, v.split())
                            elif v != '?':
                                row['solving'] = int(v)
                        elif len(k) == 1:
                            k = k.title()
                            if k not in problems_info:
                                problems_info[k] = {'short': k}
                                if 'title' in vs.header.attrs:
                                    title = vs.header.attrs['title']
                                    extra_prefix = 'problem '
                                    if title.startswith(extra_prefix):
                                        title = title[len(extra_prefix):].strip()
                                    problems_info[k]['name'] = title

                            v = re.sub(r'([0-9]+)\s+([0-9]+)\s+tr.*', r'\2 \1', v)
                            v = re.sub('tr[a-z]*', '', v)
                            v = re.sub('-*', '', v)
                            v = v.strip()
                            if not v:
                                continue

                            p = problems.setdefault(k, {})
                            if '+' in v:
                                v = v.replace(' ', '')
                                p['result'] = f'?{v}'
                            elif ' ' in v:
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
                    if row.get('place'):
                        last_place = row['place']
                    elif last_place:
                        row['place'] = last_place
                    if is_ineligible:
                        row.pop('place')
                    if 'member' not in row or row['member'].startswith(' '):
                        continue
                    result[row['member']] = row

                elements = etree.HTML(page).xpath('//div[@class="card-header"]/following-sibling::div[@class="card-body"]//li')  # noqa
                for el in elements:
                    name = ''.join([s.strip() for s in el.xpath('text()')])
                    member = f'{name} {season}'
                    row = result.setdefault(member, {'member': member, 'name': name})

                    logo = el.xpath('./img/@src')
                    if logo:
                        row.setdefault('info', {})['logo'] = urljoin(standings_url, logo[0])

                    while el is not None:
                        prv = el.getprevious()
                        if prv is not None and prv.tag == 'div' and prv.get('class') == 'card-header':
                            break
                        el = el.getparent()
                    if el is not None:
                        region = ''.join([s.strip() for s in prv.xpath('text()')])
                        row['region'] = region

                for team, row in result.items():
                    if statistics and team in statistics:
                        row.pop('info', None)
                    else:
                        info = row.get('info', {})
                        if 'logo' in info:
                            info['download_avatar_url_'] = info['logo']

            if not result:
                continue

            if statistics:
                for team, row in result.items():
                    stat = statistics.get(team)
                    if not stat:
                        continue
                    for k, v in stat.items():
                        if k not in row:
                            hidden_fields.add(k)
                            row[k] = v

            if not is_regional and any(['region' not in r for r in result.values()]):
                try:
                    url = f'https://icpc.global/api/team/wf/{year}/published'
                    page = REQ.get(url, time_out=60)
                    data = self._json_load(page)
                except Exception:
                    traceback.print_exc()
                    data = None

                if data:
                    def canonize_name(name):
                        name = name.lower()
                        name = name.replace('&', ' and ')
                        name = name.replace(',', ' ')
                        name = re.sub(r'\s{2,}', ' ', name)
                        name = re.split(r'(?:\s-\s|\s-|-\s|,\s)', name)
                        name = tuple(sorted([n.strip() for n in name]))
                        return name

                    matching = {}
                    for key, row in result.items():
                        name = row['name']
                        matching.setdefault(name, key)
                        name = canonize_name(name)
                        matching.setdefault(name, key)

                    for site in data:
                        region = site['siteName']
                        for team in site['teams']:
                            name = team['university']
                            if name not in matching:
                                name = canonize_name(name)
                            if name not in matching:
                                name = tuple(sorted(name + canonize_name(team['name'])))
                            if name not in matching:
                                logger.warning(f'Not found team = {name}')
                            else:
                                row = result[matching[name]]
                                row['region'] = region
                                for k, v in team.items():
                                    k = k.lower()
                                    if k not in row:
                                        hidden_fields.add(k)
                                        row[k] = v

            first_ac_of_all = None
            for team in result.values():
                for p_name, problem in team.get('problems', {}).items():
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
                for p_name, problem in team.get('problems', {}).items():
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
            if not without_medals and not is_regional:
                medals = self._get_medals(year)
                if medals:
                    medals = [{'name': k, 'count': v} for k, v in medals.items()]
                    options['medals'] = medals

            standings = {
                'result': result,
                'url': icpc_standings_url if is_icpc_api_standings_url else standings_url,
                'problems': list(problems_info.values()),
                'options': options,
                'hidden_fields': list(hidden_fields),
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
