#!/usr/bin/env python

import html
import json
import logging
import os
import re
import traceback
from collections import OrderedDict, defaultdict
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import coloredlogs
from django.utils.timezone import now
from lxml import etree

from submissions.models import Language, Verdict

from clist.templatetags.extras import get_item
from ranking.management.modules.codeforces import _get as codeforces_get
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from utils.strings import list_string_iou, string_iou
from utils.timetools import parse_duration

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


def canonize_name(name):
    name = name.lower()
    name = name.replace('&', ' and ')
    name = name.replace(',', ' ')
    name = re.sub(r'[^A-Za-z0-9\s+]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    return tuple(name.split())


def names_iou(name1, name2):
    canonized_name1 = canonize_name(name1)
    canonized_name2 = canonize_name(name2)
    list_iou = list_string_iou(canonized_name1, canonized_name2)

    canonized_name1_str = ''.join(canonized_name1)
    canonized_name2_str = ''.join(canonized_name2)
    str_iou = string_iou(canonized_name1_str, canonized_name2_str)

    iou = max(list_iou, str_iou)

    n = min(len(canonized_name1), len(canonized_name2))
    prefix_iou = list_string_iou(canonized_name1[:n], canonized_name2[:n])
    suffix_iou = list_string_iou(canonized_name1[-n:], canonized_name2[-n:])
    iou = max(iou, prefix_iou, suffix_iou)

    return iou


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

    def _parse_event_feed(self, event_feed, result, problems_info):
        result_names = {}
        for row in result.values():
            if row['name'] in result_names:
                raise ValueError('Duplicate name')
            result_names[row['name']] = row

        entities = defaultdict(dict)
        members = {}
        event_feed = os.path.join(os.path.dirname(__file__), event_feed)
        with open(event_feed, 'r') as fo:
            for line in fo:
                entity = json.loads(line.strip())
                entity_type = entity['type']
                if entity_type in {'contest', 'organizations'}:
                    continue

                if entity_type in {'groups', 'problems', 'judgement-types', 'languages', 'submissions',
                                   'judgements', 'runs', 'teams'}:
                    entities[entity_type][entity['data']['id']] = entity['data']

                if entity_type == 'teams':
                    team = entity['data']
                    name = (team['affiliation'] or '').strip()
                    if name in result_names:
                        members[team['id']] = result_names[name]['member']
                    elif not any(
                        group_id not in entities['groups'] or entities['groups'][group_id]['hidden']
                        for group_id in entity['data']['group_ids']
                    ):
                        raise ValueError(f'Not found team = {team}')
                    continue

        for language in entities['languages'].values():
            if Language.get(language['name']) is None:
                Language.objects.create(id=language['id'],
                                        name=language['name'],
                                        extensions=language['extensions'])

        for judgement_type in entities['judgement-types'].values():
            if Verdict.get(judgement_type['id']) is None:
                Verdict.objects.create(id=judgement_type['id'],
                                       name=judgement_type['name'],
                                       penalty=judgement_type['penalty'],
                                       solved=judgement_type['solved'])

        for problem in entities['problems'].values():
            short = problem['short_name']
            p_info = problems_info[short]
            p_info['time_limit'] = problem['time_limit']
            p_info['color'] = {'rgb': problem['rgb'], 'name': problem['color']}
            p_info['test_data_count'] = problem['test_data_count']
            p_info.setdefault('name', problem['name'])

        for run in entities['runs'].values():
            judgement = entities['judgements'][run['judgement_id']]
            run['id'] = int(run['id'])
            run['test_number'] = int(run.pop('ordinal'))
            run['verdict'] = entities['judgement-types'][run['judgement_type_id']]['id']
            run['contest_time'] = parse_duration(run['contest_time'])
            judgement.setdefault('runs', []).append(run)
        for judgement in entities['judgements'].values():
            submission = entities['submissions'][judgement['submission_id']]
            submission.setdefault('judgements', []).append(judgement)

        submissions = []
        for submission in entities['submissions'].values():
            if submission['team_id'] not in members:
                continue
            submission['contest_time'] = parse_duration(submission['contest_time'])
            if submission['contest_time'] >= self.contest.duration:
                continue
            submissions.append(submission)
        submissions.sort(key=lambda s: s['contest_time'])

        teams_attempts = defaultdict(int)
        teams_solved = set()

        for submission in submissions:
            if submission['team_id'] not in members:
                continue
            judgements = submission.pop('judgements', [])
            if len(judgements) != 1:
                logger.warning(f'len(judgements) = {len(judgements)}, submission_id = {submission["id"]}')
            judgement = max(judgements, key=lambda j: len(j.get('runs', [])))

            member = members[submission.pop('team_id')]

            problem_id = submission.pop('problem_id')
            submission['problem_short'] = entities['problems'][problem_id]['short_name']

            language_id = submission.pop('language_id')
            submission['language'] = entities['languages'][language_id]['id']

            row = result[member]

            judgement_type = entities['judgement-types'][judgement.pop('judgement_type_id')]
            submission['verdict'] = judgement_type['id']

            submission['run_time'] = judgement.pop('max_run_time')
            submission['testing'] = judgement.pop('runs', [])
            submission['valid'] = judgement.pop('valid')

            team_problem = (member, submission['problem_short'])
            if team_problem in teams_solved:
                continue
            if judgement_type['solved']:
                teams_solved.add(team_problem)
            teams_attempts[team_problem] += judgement_type['penalty'] and team_problem not in teams_solved

            submission['current_attempt'] = teams_attempts[team_problem]
            submission['current_result'] = '+' if team_problem in teams_solved else '-'
            if teams_attempts[team_problem]:
                submission['current_result'] += str(teams_attempts[team_problem])

            submission.pop('external_id', None)
            submission.pop('entry_point', None)
            submission.pop('files', None)

            row.setdefault('submissions', []).append(submission)

    def get_standings(self, users=None, statistics=None, **kwargs):
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

                if not page:
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
            has_more_members = False

            if 'zibada' in standings_url:
                names = None
                for f in (
                    lambda: page,
                    lambda: REQ.get('teams.js'),
                ):
                    try:
                        teams_page = f()
                    except FailOnGetResponse:
                        continue
                    match = re.search(r' = (?P<data>[\{\[].*?);?\s*$', teams_page, re.MULTILINE)
                    if match:
                        names = self._json_load(match.group('data'))
                        break

                try:
                    standings_page = REQ.get('standings.js')
                    match = re.search(r' = (?P<data>\{.*?);?\s*$', standings_page, re.MULTILINE)
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
                    for idx in range(len(names)):
                        teams.setdefault(str(idx), {})
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

                        more_members = names[int(tid)][1] or []
                        for more_member in more_members:
                            _, more_member = more_member.split(':', 1)
                            has_more_members = True
                            team.setdefault('_more_members', []).append({
                                'account': more_member,
                                'resource': 1,
                                'without_country': True,
                            })
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
                is_honorable_mention = False
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

                        if is_honorable_mention:
                            new_row = dict(member=f'{v} {season}', name=v)
                            result[new_row['member']] = new_row
                            continue

                        if re.search('honorable mention|in alphabetical order', v, re.I):
                            is_honorable_mention = True

                        if k in ('rank', 'rk', 'place'):
                            if not isinstance(vs, list):
                                classes = vs.column.attrs.get('class', '').split()
                                medal = vs.column.node.xpath('.//img/@alt')
                                if medal and medal[0].endswith('medal'):
                                    row['medal'] = medal[0].split()[0]
                                for medal, ending in (('gold', '🥇'), ('silver', '🥈'), ('bronze', '🥉')):
                                    if v.endswith(ending):
                                        row['medal'] = medal
                                        v = v[:-len(ending)].strip()
                                    if f'{medal}-medal' in classes:
                                        row['medal'] = medal
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

                            tr = vs[0] if isinstance(vs, list) else vs
                            if tr.row.node.attrib.get('id') in ['scoresummary']:
                                break

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
                            v = re.sub(r'([0-9]+)/([0-9]+)', r'\1 \2', v)
                            v = v.strip()
                            if not v or v == '0':
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

            if has_more_members:
                for team, row in result.items():
                    added_members = {(m['account'], m['resource']) for m in row.get('_members', [])}
                    more_members = row.pop('_more_members', [])
                    for m in more_members:
                        k = m['account'], m['resource']
                        if k not in added_members:
                            members = row.setdefault('_members', [])
                            members.append(m)
                            added_members.add(k)
                            if len(members) > 3:
                                LOG.warning(f'Too many members: {members}, team = {team}')

            if (
                not is_regional
                and any(['region' not in r for r in result.values()])
                and os.environ.get('USE_ICPC_REGION')
            ):
                try:
                    url = f'https://icpc.global/api/team/wf/{year}/published'
                    page = REQ.get(url, time_out=60)
                    data = self._json_load(page)
                except Exception:
                    traceback.print_exc()
                    data = None

                if data:
                    matching = {}
                    for key, row in result.items():
                        name = row['name']
                        matching.setdefault(name, key)
                        name = canonize_name(name)
                        matching.setdefault(name, key)

                    def add_region(name, region, team):
                        row = result[matching[name]]
                        row['region'] = region
                        for k, v in team.items():
                            k = k.lower()
                            if k not in row:
                                hidden_fields.add(k)
                                row[k] = v

                    skipped = []
                    for site in data:
                        region = site['siteName']
                        for team in site['teams']:
                            names = {team['university']}
                            for val in team['name'], site['siteName']:
                                new_names = set(names)
                                for old_name in names:
                                    new_names.add(old_name + ' ' + val)
                                    new_names.add(val + ' ' + old_name)
                                names = new_names

                            for name in names:
                                if name in matching:
                                    break
                                name = canonize_name(name)
                                if name in matching:
                                    break

                            if name not in matching:
                                skipped.append((region, team, names))
                            else:
                                add_region(name, region, team)

                    processed = set()
                    while True:
                        max_iou = 0
                        best_region = None
                        best_name = None
                        for region, team, names in skipped:
                            if team['university'] in processed:
                                continue
                            for name in names:
                                for key, row in result.items():
                                    if 'region' in row:
                                        continue
                                    iou = names_iou(name, row['name'])
                                    if iou > max_iou:
                                        max_iou = iou
                                        best_region = region
                                        best_team = team
                                        best_name = row['name']
                                        print(name)
                        if best_name is None:
                            break
                        logger.info(f'max iou = {max_iou:.3f}, best_name = {best_name}')
                        if max_iou < 0.9:
                            break
                        processed.add(best_team['university'])
                        add_region(best_name, best_region, best_team)

            first_ac_of_all = None
            for team in result.values():
                for p_name, problem in team.get('problems', {}).items():
                    p_info = problems_info[p_name]
                    if not problem['result'].startswith('+'):
                        continue
                    time = problem['time']
                    if 'first_ac' not in p_info or time < p_info['_first_ac_time']:
                        p_info['_first_ac_time'] = time
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
                        if problem['time'] == p_info['_first_ac_time']:
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

            if 'use_codeforces_list' in self.info and os.environ.get('USE_CODEFORCES_LIST'):
                cf_info = self.info['use_codeforces_list']
                page = codeforces_get(cf_info['url'])
                fields = [cf_info['fields']['university'], *cf_info['fields']['members']]
                matches = re.finditer('<table[^>]*>.*?</table>', page, re.DOTALL)
                names_rows = {}
                for row in result.values():
                    region = row.get('region')
                    name = row['name']
                    if region and name.startswith(region):
                        name = name[len(region):].strip()
                    names_rows[name] = row
                skipped = []

                def add_team(university, handles):
                    result_row = names_rows[university]
                    members = result_row.setdefault('_members', [])
                    accounts = {m['account'] for m in members}
                    for handle in handles:
                        if handle in accounts:
                            continue
                        members.append({
                            'account': handle,
                            'resource': cf_info['resource'],
                            'without_country': True,
                        })

                for match in matches:
                    html_table = match.group(0)
                    table = parsed_table.ParsedTable(html_table)
                    columns = [col.value for col in table.header.columns]
                    if len(set(columns) & set(fields)) != len(set(fields)):
                        continue
                    for row in table:
                        university = row.get(cf_info['fields']['university']).value
                        handles = []
                        for member in cf_info['fields']['members']:
                            val = row.get(member)
                            hrefs = val.column.node.xpath('.//a/@href')
                            if not hrefs:
                                continue
                            handle = hrefs[0].strip('/').split('/')[-1]
                            handles.append(handle)
                        if university not in names_rows:
                            skipped.append((university, handles))
                            continue
                        add_team(university, handles)

                candidates = []
                for university, handles in skipped:
                    best_iou = 0
                    university_re = university
                    university_re = re.sub('[- —,()"]+', '[- —,()"]+', university_re)
                    university_re = re.sub(r'\b[A-Z]+\b',
                                           lambda m: ''.join(f'{c}[^A-Z]*' for c in m.group(0)),
                                           university_re)
                    for name, row in names_rows.items():
                        iou = names_iou(name, university)
                        if re.match(university_re, name):
                            iou = max(iou, 0.999)
                        if iou > best_iou:
                            best_iou = iou
                            best_name = name
                    candidates.append((best_iou, best_name, university, handles))
                candidates.sort(reverse=True)
                processed = set()
                for best_iou, best_name, university, handles in candidates:
                    if university in processed:
                        continue
                    processed.add(university)
                    if best_iou < 0.85:
                        logger_func = logger.warning
                    else:
                        logger_func = logger.info
                        add_team(best_name, handles)
                    logger_func(f'best_iou = {best_iou:.3f}, best_name = {best_name}, university = {university}')

            event_feed = get_item(self.info, 'standings._event_feed')
            if event_feed:
                self._parse_event_feed(event_feed, result, problems_info)

            standings = {
                'result': result,
                'url': icpc_standings_url if is_icpc_api_standings_url else standings_url,
                'problems': list(problems_info.values()),
                'options': options,
                'hidden_fields': list(hidden_fields),
                'series': 'icpc',
            }

            return standings

        raise ExceptionParseStandings(f'Not found standings url from {standings_urls}')
