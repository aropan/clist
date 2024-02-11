#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from math import isclose
from urllib.parse import parse_qs, quote, urljoin

import dateutil.parser
import tqdm
from lxml import etree

from clist.templatetags.extras import as_number, asfloat, toint
from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule, parsed_table, save_proxy
from ranking.management.modules.excepts import ExceptionParseAccounts, ExceptionParseStandings, InitModuleException
from utils.requester import FailOnGetResponse


class Statistic(BaseModule):
    LEGACY_PROXY_PATH = 'logs/legacy/topcoder.proxy'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._handle = conf.TOPCODER_HANDLE
        self._password = conf.TOPCODER_PASSWORD

        new_expires = int((datetime.now() + timedelta(days=100)).timestamp())
        for c in REQ.get_raw_cookies():
            if c.domain and c.domain.endswith('.topcoder.com') and c.expires is not None:
                c.expires = max(c.expires, new_expires)
                REQ.update_cookie(c)
        # cookies = {
        #     cookie.name for cookie in REQ.get_raw_cookies()
        #     if 'topcoder.com' in cookie.domain
        #     and (
        #         cookie.expires is None
        #         or cookie.expires > datetime.now().timestamp()
        #     )
        # }
        # assert 'tcjwt' in cookies or 'tcsso' in cookies
        # if 'tcjwt' not in cookies or 'tcsso' not in cookies:
        #     page = REQ.get('https://topcoder.com/login')
        #     match = re.search(r'src="(app\.[^"]*.js|[^"]*setupAuth0WithRedirect.js)"', page)
        #     url = urljoin(REQ.last_url, match.group(1))
        #     page = REQ.get(url)
        #     match = re.search(r'''clientId\s*[:=]\s*["']([^"']*)''', page)
        #     client_id = match.group(1)
        #     params = {
        #         "client_id": client_id,
        #         "connection": "TC-User-Database",
        #         "device": "Browser",
        #         "grant_type": "password",
        #         "password": self._password,
        #         "response_type": "token",
        #         "scope": "openid profile offline_access",
        #         "sso": False,
        #         "username": self._handle,
        #     }
        #     page = REQ.get('https://topcoder.auth0.com/oauth/ro', post=params)
        #     data = json.loads(page)

        #     params = {"param": {"externalToken": data['id_token'], "refreshToken": data['refresh_token']}}
        #     page = REQ.get(
        #         'https://api.topcoder.com/v3/authorizations',
        #         post=json.dumps(params).encode('utf-8'),
        #         headers={'Content-Type': 'application/json;charset=UTF-8'}
        #     )

    @staticmethod
    def _dict_as_number(d):
        ret = OrderedDict()
        for k, v in d.items():
            k = k.strip().lower().replace(' ', '_')
            if not k or not v or v == 'N/A':
                continue
            vi = toint(v)
            if vi is not None:
                v = vi
            else:
                vf = asfloat(v.replace(',', '.'))
                if vf is not None:
                    v = vf
            ret[k] = v
        return ret

    def get_standings(self, users=None, statistics=None):
        result = {}
        hidden_fields = []
        fields_types = {}
        order = None
        writers = defaultdict(int)

        start_time = self.start_time.replace(tzinfo=None)

        req = REQ.with_proxy(
            time_limit=10,
            n_limit=50,
            filepath_proxies=os.path.join(os.path.dirname(__file__), '.topcoder.proxies'),
            connect=lambda req: req.get('https://www.topcoder.com/', n_attempts=1),
            attributes=dict(n_attempts=5),
        )

        if not self.standings_url and datetime.now() - start_time < timedelta(days=30):
            opt = 0.61803398875

            def canonize_title(value):
                value = value.lower()
                value = re.sub(r'\s+-[^-]+$', '', value)
                value = re.sub(r'\bsingle\s+round\s+match\b', 'srm', value)
                value = re.sub(r'\bmarathon\s+match\b', 'mm', value)
                value = re.sub(r'[0-9]*([0-9]{2})\s*tco(\s+)', r'tco\1\2', value)
                value = re.sub(r'tco\s*[0-9]*([0-9]{2})(\s+)', r'tco\1\2', value)
                value = re.sub(r'^[0-9]{2}([0-9]{2})(\s+)', r'tco\1\2', value)
                return set(re.split('[^A-Za-z0-9]+', value))

            def process_match(date, title, url):
                nonlocal opt

                if abs(date - start_time) > timedelta(days=2):
                    return

                a1 = canonize_title(title)
                a2 = canonize_title(self.name)
                intersection = 0
                for w1 in a1:
                    for w2 in a2:
                        if w1.isdigit() or w2.isdigit():
                            if w1 == w2:
                                intersection += 1
                                break
                        elif w1.startswith(w2) or w2.startswith(w1):
                            intersection += 1
                            break
                union = len(a1) + len(a2) - intersection
                iou = intersection / union
                if iou > opt:
                    opt = iou
                    self.standings_url = url

            url = 'https://www.topcoder.com/tc?module=MatchList&nr=100500'
            page = req.get(url)
            re_round_overview = re.compile(
                r'''
(?:<td[^>]*>(?:
[^<]*<a[^>]*href="(?P<url>[^"]*/stat[^"]*rd=(?P<rd>[0-9]+)[^"]*)"[^>]*>(?P<title>[^<]*)</a>[^<]*|
(?P<date>[0-9]+\.[0-9]+\.[0-9]+)
)</td>[^<]*){2}
                ''',
                re.VERBOSE,
            )
            matches = re_round_overview.finditer(str(page))
            for match in matches:
                date = datetime.strptime(match.group('date'), '%m.%d.%Y')
                process_match(date, match.group('title'), urljoin(url, match.group('url')))

            url = 'https://www.topcoder.com/tc?module=BasicData&c=dd_round_list'
            page = req.get(url)
            root = ET.fromstring(page)
            for child in root:
                data = {}
                for field in child:
                    data[field.tag] = field.text
                date = dateutil.parser.parse(data['date'])
                url = 'https://www.topcoder.com/stat?c=round_overview&er=5&rd=' + data['round_id']
                process_match(date, data['full_name'], url)

        for url in self.url, self.standings_url:
            if url:
                match = re.search('/challenges/(?P<cid>[0-9]+)', url)
                if match:
                    challenge_id = match.group('cid')
                    break
        else:
            challenge_id = None

        if 'community.topcoder.com/pl' in self.standings_url:
            page = req.get(self.standings_url)
            tables = re.findall(r'<table[^>]*>\s*<tr[^>]*>\s*<t[^>]*colspan="?[23]"?[^>]*>.*?</table>', page, re.DOTALL)
            for table in tables:
                rows = parsed_table.ParsedTable(table, default_header_rowspan=2)
                for row in rows:
                    row = {k.lower(): v.value for k, v in row.items()}
                    row['member'] = row.pop('handle')
                    row['solving'] = as_number(row.pop('score'), force=True)
                    result[row['member']] = row

            last_rank, last_score = None, None
            for rank, row in enumerate(sorted(result.values(), key=lambda x: x['solving'], reverse=True), start=1):
                if last_score is None or not isclose(last_score, row['solving']):
                    last_score = row['solving']
                    last_rank = rank
                row['place'] = last_rank

            problems_info = None
        elif challenge_id:  # marathon match
            url = conf.TOPCODER_API_MM_URL_FORMAT.format(challenge_id)
            page = req.get(url)
            data = json.loads(page)
            problems_info = []
            hidden_fields.extend(['time', 'submits', 'style'])
            fields_types = {'delta_rank': ['delta'], 'delta_score': ['delta']}
            order = ['place_as_int', '-solving', 'addition__provisional_rank', '-addition__provisional_score']
            for row in data:
                handle = row.pop('member')
                r = result.setdefault(handle, OrderedDict())
                r['member'] = handle
                r['place'] = row.pop('finalRank', None)
                r['provisional_rank'] = row.pop('provisionalRank', None)
                r['style'] = row.pop('style')
                if r['place'] and r['provisional_rank']:
                    r['delta_rank'] = r['provisional_rank'] - r['place']
                submissions = row.pop('submissions')
                has_solution = False
                for s in submissions:
                    score = s.get('finalScore')
                    if not score or score == '-':
                        if 'provisional_score' not in r:
                            p_score = s.pop('provisionalScore', None)
                            if isinstance(p_score, str):
                                p_score = asfloat(p_score)
                            if p_score is not None:
                                r['provisional_score'] = round(p_score, 2) if p_score >= 0 else False
                                r['time'] = s['created']
                                has_solution = True
                        continue
                    r['solving'] = score
                    r['solved'] = {'solving': int(score > 0)}
                    p_score = s.pop('provisionalScore')
                    if isinstance(p_score, str):
                        p_score = asfloat(p_score)
                    if p_score is not None and p_score > 0:
                        r['provisional_score'] = round(p_score, 2)
                        r['delta_score'] = round(score - p_score, 2)
                    r['time'] = s['created']
                    has_solution = True
                    break
                if not has_solution:
                    continue
                r['submits'] = len(submissions)
            if not result:
                raise ExceptionParseStandings('empty standings')
            if len(result) < 3:
                raise ExceptionParseStandings('not enough participants')
        else:  # single round match
            if not self.standings_url:
                raise InitModuleException('Not set standings url for %s' % self.name)
            url = self.standings_url + '&nr=100000042'
            page = req.get(url, time_out=100)
            result_urls = re.findall(r'<a[^>]*href="(?P<url>[^"]*)"[^>]*>Results</a>', str(page), re.I)
            if not result_urls:
                raise ExceptionParseStandings('not found result urls')

            dd_round_results = {}
            match = re.search('rd=(?P<rd>[0-9]+)', url)
            if match:
                rd = match.group('rd')
                url = f'https://www.topcoder.com/tc?module=BasicData&c=dd_round_results&rd={rd}'
                try:
                    dd_round_results_page = req.get(url)
                    root = ET.fromstring(dd_round_results_page)
                    for child in root:
                        data = {}
                        for field in child:
                            data[field.tag] = field.text
                        handle = data.pop('handle')
                        dd_round_results[handle] = self._dict_as_number(data)
                except FailOnGetResponse:
                    pass

            hidden_fields.extend(['coding_phase', 'challenge_phase', 'system_test', 'point_total', 'room'])

            matches = re.finditer('<table[^>]*>.*?</table>', page, re.DOTALL)
            problems_sets = []
            for match in matches:
                problems = re.findall(
                    '<a[^>]*href="(?P<href>[^"]*(?:c=problem_statement[^"]*|pm=(?P<key>[0-9]+)[^"]*){2})"[^>]*>(?P<name>[^/]*)</a>',  # noqa
                    match.group(),
                    re.IGNORECASE,
                )
                if problems:
                    problems_sets.append([
                        {'short': n, 'url': urljoin(url, u), 'code': k}
                        for u, k, n in problems
                    ])

            problems_info = dict() if len(problems_sets) > 1 else list()
            with_adv = False
            for problems_set, result_url in zip(problems_sets, result_urls):
                url = urljoin(self.standings_url, result_url + '&em=1000000042')
                url = url.replace('&amp;', '&')
                division = int(parse_qs(url)['dn'][0])
                division_str = 'I' * division

                with PoolExecutor(max_workers=3) as executor:

                    def fetch_problem(p):
                        page = req.get(p['url'], time_out=30)
                        match = re.search('<a[^>]*href="(?P<href>[^"]*module=ProblemDetail[^"]*)"[^>]*>', page)
                        page = req.get(urljoin(p['url'], match.group('href')), time_out=30)
                        matches = re.findall(r'<td[^>]*class="statTextBig"[^>]*>(?P<key>[^<]*)</td>\s*<td[^>]*>(?P<value>.*?)</td>', page, re.DOTALL)  # noqa
                        for key, value in matches:
                            key = key.strip().rstrip(':').lower()
                            if key == 'categories':
                                tags = [t.strip().lower() for t in value.split(',')]
                                tags = [t for t in tags if t]
                                if tags:
                                    p['tags'] = tags
                            elif key.startswith('writer') or key.startswith('tester'):
                                key = key.rstrip('s') + 's'
                                p[key] = re.findall('(?<=>)[^<>,]+(?=<)', value)
                        for w in p.get('writers', []):
                            writers[w] += 1

                        info = p.setdefault('info', {})
                        matches = re.finditer('<table[^>]*paddingTable2[^>]*>.*?</table>', page, re.DOTALL)
                        for match in matches:
                            html_table = match.group(0)
                            rows = parsed_table.ParsedTable(html_table)
                            for row in rows:
                                key, value = None, None
                                for k, v in row.items():
                                    if k == "":
                                        key = v.value
                                    elif k and division_str in k.split():
                                        value = v.value
                                if key and value:
                                    key = re.sub(' +', '_', key.lower())
                                    info[key] = value
                                    if key == 'point_value':
                                        value = toint(value) or asfloat(value)
                                        if value is not None:
                                            p['full_score'] = value
                        return p

                    for p in tqdm.tqdm(executor.map(fetch_problem, problems_set), total=len(problems_set)):
                        d = problems_info
                        if len(problems_sets) > 1:
                            d = d.setdefault('division', OrderedDict())
                            d = d.setdefault(division_str, [])
                        d.append(p)

                if not users and users is not None:
                    continue

                page = req.get(url)
                rows = etree.HTML(page).xpath("//tr[@valign='middle']")
                header = None
                url_infos = []
                for row in rows:
                    r = parsed_table.ParsedTableRow(row)
                    if len(r.columns) < 10:
                        continue
                    values = [c.value for c in r.columns]
                    if header is None:
                        header = values
                        continue

                    d = OrderedDict(list(zip(header, values)))
                    handle = d.pop('Coders').strip()
                    d = self._dict_as_number(d)
                    if users and handle not in users:
                        continue

                    row = result.setdefault(handle, OrderedDict())
                    row.update(d)

                    if not row.get('new_rating') and not row.get('old_rating') and not row.get('rating_change'):
                        row.pop('new_rating', None)
                        row.pop('old_rating', None)
                        row.pop('rating_change', None)

                    row['member'] = handle
                    row['place'] = row.pop('division_placed', None)
                    if not row['place']:
                        row.pop('place')
                    row['solving'] = row['point_total']
                    row['solved'] = {'solving': 0}
                    row['division'] = 'I' * division

                    if 'adv.' in row:
                        row['advanced'] = row.pop('adv.').lower().startswith('y')
                        with_adv |= row['advanced']

                    url_info = urljoin(url, r.columns[0].node.xpath('a/@href')[0])
                    url_infos.append(url_info)

                def fetch_solution(url):
                    ret = None
                    try:
                        page = req.get(url, time_out=60)
                        match = re.search('<td[^>]*class="problemText"[^>]*>(?P<solution>.*?)</td>',
                                          page,
                                          re.DOTALL | re.IGNORECASE)
                        if match:
                            ret = html.unescape(match.group('solution'))
                            ret = ret.strip()
                            ret = ret.replace('<BR>', '\n')
                            ret = ret.replace('\xa0', ' ')
                    except FailOnGetResponse:
                        pass
                    return ret

                n_failed_fetch_info = 0

                def fetch_info(url):
                    nonlocal n_failed_fetch_info
                    if n_failed_fetch_info > 10:
                        return
                    match = None
                    try:
                        page = req.get(url, time_out=10)
                        match = re.search('class="coderBrackets">.*?<a[^>]*>(?P<handle>[^<]*)</a>',
                                          page,
                                          re.IGNORECASE)
                    except FailOnGetResponse:
                        pass

                    if not match:
                        n_failed_fetch_info += 1
                        return

                    handle = html.unescape(match.group('handle').strip())

                    match = re.search(r'&nbsp;Room\s*(?P<room>[0-9]+)', page)
                    room = match.group('room') if match else None

                    matches = re.finditer(r'''
                        <td[^>]*>[^<]*<a[^>]*href="(?P<url>[^"]*c=problem_solution[^"]*)"[^>]*>(?P<short>[^<]*)</a>[^<]*</td>[^<]*
                        <td[^>]*>[^<]*</td>[^<]*
                        <td[^>]*>[^<]*</td>[^<]*
                        <td[^>]*>(?P<time>[^<]*)</td>[^<]*
                        <td[^>]*>(?P<status>[^<]*)</td>[^<]*
                        <td[^>]*>(?P<result>[^<]*)</td>[^<]*
                    ''', page, re.VERBOSE | re.IGNORECASE)
                    problems = {}
                    n_fetch_solution = 0
                    for match in matches:
                        d = match.groupdict()
                        short = d.pop('short')
                        solution_url = urljoin(url, d['url'])
                        d['url'] = solution_url
                        d = self._dict_as_number(d)
                        if d['status'] in ['Challenge Succeeded', 'Failed System Test']:
                            d['result'] = -d['result']
                        if abs(d['result']) < 1e-9:
                            d.pop('result')
                        if re.match('^[0.:]+$', d['time']):
                            d.pop('time')
                        else:
                            time_in_seconds = 0
                            for t in d['time'].split(':'):
                                time_in_seconds = time_in_seconds * 60 + asfloat(t)
                            d['time_in_seconds'] = time_in_seconds

                        solution = (statistics or {}).get(handle, {}).get('problems', {}).get(short, {}).get('solution')
                        if not solution:
                            n_fetch_solution += 1
                            solution = fetch_solution(solution_url)
                        d['solution'] = solution

                        problems[short] = d

                    challenges = []
                    matches = re.finditer(r'''
                        <td[^>]*>[^<]*<a[^>]*href="[^"]*module=MemberProfile[^"]*"[^>]*>(?P<target>[^<]*)</a>[^<]*</td>[^<]*
                        <td[^>]*>(?P<problem>[^<]*)</td>[^<]*
                        <td[^>]*>(?P<status>[^<]*)</td>[^<]*
                        <td[^>]*>(?P<time>[^<]*)</td>[^<]*
                        <td[^>]*>(?P<result>[^<]*)</td>[^<]*
                        <td[^>]*>[^<]*<a[^>]*href="(?P<url>[^"]*)"[^>]*>\s*details\s*</a>[^<]*</td>[^<]*
                    ''', page, re.VERBOSE | re.IGNORECASE)
                    for match in matches:
                        d = match.groupdict()
                        d = {k: v.strip() for k, v in d.items()}
                        d['result'] = float(d['result'].replace(',', '.'))
                        d['url'] = urljoin(url, d['url'])

                        p = problems.setdefault(d['problem'], {})
                        p.setdefault('extra_score', 0)
                        p['extra_score'] += d['result']
                        p.setdefault('extra_info', []).append(f'{d["target"]}: {d["result"]}')
                        challenges.append(d)

                    return url, handle, room, problems, challenges, n_fetch_solution

                with PoolExecutor(max_workers=20) as executor, tqdm.tqdm(total=len(url_infos)) as pbar:
                    n_fetch_solution = 0
                    for info in executor.map(fetch_info, url_infos):
                        if info is None:
                            continue
                        url, handle, room, problems, challenges, n_sol = info
                        n_fetch_solution += n_sol
                        pbar.set_description(f'div{division} {url}')
                        pbar.set_postfix(n_solution=n_fetch_solution, n_failed_fetch_info=n_failed_fetch_info)
                        pbar.update()
                        if handle is not None:
                            if handle not in result:
                                LOG.error(f'{handle} not in result, url = {url}')
                            row = result[handle]
                            row['url'] = url
                            if room:
                                row['room'] = room
                            row['problems'] = problems
                            row['challenges'] = challenges
                            for p in problems.values():
                                if p.get('result', 0) > 1e-9:
                                    row['solved']['solving'] += 1
                            if challenges:
                                h = row.setdefault('hack', {
                                    'title': 'challenges',
                                    'successful': 0,
                                    'unsuccessful': 0,
                                })
                                for c in challenges:
                                    h['successful' if c['status'].lower() == 'yes' else 'unsuccessful'] += 1

            if not with_adv:
                for row in result.values():
                    row.pop('advanced', None)

            if dd_round_results:
                fields = set()
                hidden_fields_set = set(hidden_fields)
                for data in result.values():
                    for field in data.keys():
                        fields.add(field)

                k_mapping = {'new_vol': 'new_volatility', 'advanced': None}
                for handle, data in dd_round_results.items():
                    if handle not in result:
                        continue
                    row = result[handle]

                    for k, v in data.items():
                        k = k_mapping.get(k, k)
                        if k and k not in fields:
                            if k in {'new_rating', 'old_rating'} and not v:
                                continue
                            row[k] = v
                            if k not in hidden_fields_set:
                                hidden_fields_set.add(k)
                                hidden_fields.append(k)
                            ks = k.split('_')
                            if ks[0] == 'level' and ks[-1] == 'language' and v and v.lower() != 'unspecified':
                                idx = {'one': 0, 'two': 1, 'three': 2}.get(ks[1], None)
                                d = problems_info
                                if len(problems_sets) > 1:
                                    d = d['division'][row['division']]
                                if (
                                    idx is not None
                                    and 0 <= idx < len(d)
                                    and 'problems' in row
                                    and d[idx]['short'] in row['problems']
                                ):
                                    row['problems'][d[idx]['short']]['language'] = v
        save_proxy(req, Statistic.LEGACY_PROXY_PATH)
        req.__exit__()

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
            'hidden_fields': hidden_fields,
            'fields_types': fields_types,
            'options': {
                'fixed_fields': [('hack', 'Challenges')],
            },
            'kind': 'algorithm' if 'topcoder.com/stat?' in self.standings_url else 'other',
        }

        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers

        if re.search(r'\bfinals?(?:\s+rounds?)?$', self.name, re.I):
            standings['options']['medals'] = [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]

        if order:
            standings['options']['order'] = order

        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        def parse_xml(page):
            root = ET.fromstring(page)
            for child in root:
                data = {}
                for field in child:
                    data[field.tag] = field.text
                yield data

        active_algorithm_list_url = 'https://www.topcoder.com/tc?module=BasicData&c=dd_active_algorithm_list'
        with REQ.with_proxy(
            time_limit=10,
            n_limit=20,
            filepath_proxies=os.path.join(os.path.dirname(__file__), '.topcoder.proxies'),
            connect=lambda req: req.get(active_algorithm_list_url, n_attempts=1),
            attributes=dict(n_attempts=5),
        ) as req:
            page = req.proxer.get_connect_ret()
            dd_active_algorithm = {}
            for data in parse_xml(page):
                dd_active_algorithm[data.pop('handle')] = data

            def fetch_profile(user):
                url = f'https://api.topcoder.com/v5/members/{quote(user)}'
                req.proxer.set_connect_func(lambda req: req.get(url))

                ret = {}
                try:
                    page = req.get(url)
                except FailOnGetResponse as e:
                    if e.code == 404:
                        return None
                    return False
                ret = json.loads(page)
                if 'error' in ret and isinstance(ret['error'], dict) and ret['error'].get('value') == 404:
                    ret = {'handle': user, 'action': 'remove'}
                if 'handle' not in ret:
                    if not ret or 'error' in ret:
                        ret['delta'] = timedelta(days=7)
                    ret['handle'] = user

                for src, dst in (
                    ('homeCountryCode', 'country'),
                    ('competitionCountryCode', 'country'),
                    ('description', 'shortBio'),
                    ('photoURL', 'photoLink'),
                    ('handleLower', 'handle'),
                ):
                    val = ret.pop(src, None)
                    if val and not ret.get(dst):
                        ret[dst] = val
                if not ret.get('photoLink'):
                    ret.pop('photoLink', None)
                if user in dd_active_algorithm:
                    data = dd_active_algorithm[user]
                    if 'alg_vol' in data:
                        ret['volatility'] = toint(data['alg_vol'])
                    if 'alg_rating' in data:
                        ret['rating'] = toint(data['alg_rating'])
                elif 'userId' in ret:
                    url = f'https://www.topcoder.com/tc?module=BasicData&c=dd_rating_history&cr={ret["userId"]}'
                    page = req.get(url)
                    max_rating_order = -1
                    ret['rating'], ret['volatility'], n_rating = None, None, 0
                    for data in parse_xml(page):
                        n_rating += 1
                        rating_order = as_number(data['rating_order'])
                        if rating_order > max_rating_order:
                            max_rating_order = rating_order
                            ret['rating'] = as_number(data['new_rating'])
                            ret['volatility'] = as_number(data['volatility'])
                    if ret['rating'] == 0 and n_rating <= 3:
                        ret['rating'], ret['volatility'] = None, None
                for rating in ret.get('ratingSummary', []):
                    if rating['name'].lower() == 'algorithm' and 'rating' not in ret:
                        ret['rating'] = rating['rating']
                        ret['volatility'] = None
                return ret

            with PoolExecutor(max_workers=4) as executor:
                for user, data in zip(users, executor.map(fetch_profile, users)):
                    if not data:
                        if data is None:
                            yield {'delete': True}
                        elif data is False:
                            yield {'skip': True}
                        else:
                            raise ExceptionParseAccounts('Unknown error')
                        continue
                    data['handle'] = data['handle'].strip()
                    assert user.lower() == data['handle'].lower()
                    if pbar:
                        pbar.update()
                    yield {'info': data}

            save_proxy(req, Statistic.LEGACY_PROXY_PATH)
