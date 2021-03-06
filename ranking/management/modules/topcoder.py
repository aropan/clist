#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import json
import html
from collections import OrderedDict, defaultdict
from urllib.parse import urljoin, parse_qs
from lxml import etree
from datetime import timedelta, datetime
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from pprint import pprint
from time import sleep

import tqdm

from ranking.management.modules.common import LOG, REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException, ExceptionParseStandings
from ranking.management.modules import conf
from utils.requester import FailOnGetResponse


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self._handle = conf.TOPCODER_HANDLE
        self._password = conf.TOPCODER_PASSWORD

        new_expires = int((datetime.now() + timedelta(days=100)).timestamp())
        for c in REQ.get_raw_cookies():
            if 'topcoder.com' in c.domain:
                print(c.name, datetime.fromtimestamp(c.expires))
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
            if ',' in v:
                v = float(v.replace(',', '.'))
            elif re.match('^-?[0-9]+$', v):
                v = int(v)
            ret[k] = v
        return ret

    def get_standings(self, users=None, statistics=None):
        result = {}
        writers = defaultdict(int)

        start_time = self.start_time.replace(tzinfo=None)

        if not self.standings_url and datetime.now() - start_time < timedelta(days=30):
            re_round_overview = re.compile(
                r'''
(?:<td[^>]*>
    (?:
        [^<]*<a[^>]*href="(?P<url>[^"]*/stat[^"]*rd=(?P<rd>[0-9]+)[^"]*)"[^>]*>(?P<title>[^<]*)</a>[^<]*|
        (?P<date>[0-9]+\.[0-9]+\.[0-9]+)
    )</td>[^<]*
){2}
                ''',
                re.VERBOSE,
            )
            for url in [
                'https://www.topcoder.com/tc?module=MatchList&nr=100500',
                'https://community.topcoder.com/longcontest/stats/?module=MatchList&nr=100500',
            ]:
                page = REQ.get(url)
                matches = re_round_overview.finditer(str(page))
                opt = 0.61803398875
                for match in matches:
                    date = datetime.strptime(match.group('date'), '%m.%d.%Y')
                    if abs(date - start_time) < timedelta(days=2):
                        title = match.group('title')
                        intersection = len(set(title.split()) & set(self.name.split()))
                        union = len(set(title.split()) | set(self.name.split()))
                        iou = intersection / union
                        if iou > opt:
                            opt = iou
                            self.standings_url = urljoin(url, match.group('url'))

        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

        url = self.standings_url + '&nr=100000042'
        page = REQ.get(url, time_out=100)
        result_urls = re.findall(r'<a[^>]*href="(?P<url>[^"]*)"[^>]*>Results</a>', str(page), re.I)

        if not result_urls:  # marathon match
            match = re.search('<[^>]*>Problem:[^<]*<a[^>]*href="(?P<href>[^"]*)"[^>]*>(?P<name>[^<]*)<', page)
            if not match:
                raise ExceptionParseStandings('not found problem')
            problem_name = match.group('name').strip()
            problems_info = [{
                'short': problem_name,
                'url': urljoin(url, match.group('href').replace('&amp;', '&'))
            }]
            rows = etree.HTML(page).xpath("//table[contains(@class, 'stat')]//tr")
            header = None
            for row in rows:
                r = parsed_table.ParsedTableRow(row)
                if len(r.columns) < 8:
                    continue
                values = [c.value.strip().replace(u'\xa0', '') for c in r.columns]
                if header is None:
                    header = values
                    continue

                d = OrderedDict(list(zip(header, values)))
                handle = d.pop('Handle').strip()
                d = self._dict_as_number(d)
                if 'rank' not in d or users and handle not in users:
                    continue
                row = result.setdefault(handle, OrderedDict())
                row.update(d)

                score = row.pop('final_score' if 'final_score' in row else 'provisional_score')
                row['member'] = handle
                row['place'] = row.pop('rank')
                row['solving'] = score
                row['solved'] = {'solving': 1 if score > 0 else 0}

                problems = row.setdefault('problems', {})
                problem = problems.setdefault(problem_name, {})
                problem['result'] = score

                history_index = values.index('submission history')
                if history_index:
                    column = r.columns[history_index]
                    href = column.node.xpath('a/@href')
                    if href:
                        problem['url'] = urljoin(url, href[0])
        else:  # single round match
            matches = re.finditer('<table[^>]*>.*?</table>', page, re.DOTALL)
            problems_sets = []
            for match in matches:
                problems = re.findall(
                    '<a[^>]*href="(?P<href>[^"]*c=problem_statement[^"]*)"[^>]*>(?P<name>[^/]*)</a>',
                    match.group(),
                    re.IGNORECASE,
                )
                if problems:
                    problems_sets.append([
                        {'short': n, 'url': urljoin(url, u)}
                        for u, n in problems
                    ])

            problems_info = dict() if len(problems_sets) > 1 else list()
            for problems_set, result_url in zip(problems_sets, result_urls):
                url = urljoin(self.standings_url, result_url + '&em=1000000042')
                url = url.replace('&amp;', '&')
                division = int(parse_qs(url)['dn'][0])

                with PoolExecutor(max_workers=3) as executor:
                    def fetch_problem(p):
                        errors = set()
                        for attempt in range(3):
                            try:
                                page = REQ.get(p['url'], time_out=30)
                                match = re.search('<a[^>]*href="(?P<href>[^"]*module=ProblemDetail[^"]*)"[^>]*>', page)
                                page = REQ.get(urljoin(p['url'], match.group('href')), time_out=30)
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
                            except Exception as e:
                                errors.add(f'error parse problem info {p}: {e}')
                                sleep(5 + attempt)
                        else:
                            errors = None
                        if errors:
                            LOG.error(errors)

                        return p

                    for p in tqdm.tqdm(executor.map(fetch_problem, problems_set), total=len(problems_set)):
                        d = problems_info
                        if len(problems_sets) > 1:
                            d = d.setdefault('division', OrderedDict())
                            d = d.setdefault('I' * division, [])
                        d.append(p)

                if not users and users is not None:
                    continue

                page = REQ.get(url)
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
                    row['solving'] = row['point_total']
                    row['solved'] = {'solving': 0}
                    row['division'] = 'I' * division

                    if 'adv.' in row:
                        row['advanced'] = row.pop('adv.').lower().startswith('y')

                    url_info = urljoin(url, r.columns[0].node.xpath('a/@href')[0])
                    url_infos.append(url_info)

                def fetch_solution(url):
                    for i in range(2):
                        try:
                            page = REQ.get(url, time_out=60)
                            match = re.search('<td[^>]*class="problemText"[^>]*>(?P<solution>.*?)</td>',
                                              page,
                                              re.DOTALL | re.IGNORECASE)
                            if not match:
                                break
                            ret = html.unescape(match.group('solution'))
                            ret = ret.strip()
                            ret = ret.replace('<BR>', '\n')
                            ret = ret.replace('\xa0', ' ')
                            return ret
                        except FailOnGetResponse:
                            sleep(i * 10 + 3)
                    return None

                n_failed_fetch_info = 0

                def fetch_info(url):
                    nonlocal n_failed_fetch_info
                    if n_failed_fetch_info > 10:
                        return
                    delay = 10
                    for _ in range(3):
                        try:
                            page = REQ.get(url, time_out=delay)
                            break
                        except Exception:
                            sleep(delay + _)
                    else:
                        n_failed_fetch_info += 1
                        return

                    match = re.search('class="coderBrackets">.*?<a[^>]*>(?P<handle>[^<]*)</a>', page, re.IGNORECASE)
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
                        pbar.set_postfix(n_solution=n_fetch_solution)
                        pbar.update()
                        if handle is not None:
                            if handle not in result:
                                LOG.error(f'{handle} not in result, url = {url}')
                            result[handle]['url'] = url
                            if room:
                                result[handle]['room'] = room
                            result[handle]['problems'] = problems
                            result[handle]['challenges'] = challenges
                            for p in problems.values():
                                if p.get('result', 0) > 1e-9:
                                    result[handle]['solved']['solving'] += 1
                            if challenges:
                                h = result[handle].setdefault('hack', {
                                    'title': 'challenges',
                                    'successful': 0,
                                    'unsuccessful': 0,
                                })
                                for c in challenges:
                                    h['successful' if c['status'].lower() == 'yes' else 'unsuccessful'] += 1

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
            'options': {
                'fixed_fields': [('hack', 'Challenges')],
            },
        }

        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers

        if re.search(r'\bfinals?(?:\s+rounds?)?$', self.name, re.I):
            standings['options']['medals'] = [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]

        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        def fetch_profile(user):
            url = f'http://api.topcoder.com/v2/users/{user}'
            ret = {}
            for _ in range(2):
                try:
                    page = REQ.get(url)
                    ret = json.loads(page)
                    if 'error' in ret:
                        if isinstance(ret['error'], dict) and ret['error'].get('value') == 404:
                            ret = {'handle': user, 'action': 'remove'}
                        else:
                            continue
                    break
                except Exception:
                    pass
                sleep(1)
            if 'handle' not in ret:
                if not ret:
                    ret['delta'] = timedelta(days=30)
                ret['handle'] = user
            if not ret.get('photoLink'):
                ret.pop('photoLink', None)
            return ret

        ret = []
        with PoolExecutor(max_workers=4) as executor:
            for user, data in zip(users, executor.map(fetch_profile, users)):
                data['handle'] = data['handle'].strip()
                assert user.lower() == data['handle'].lower()
                if pbar:
                    pbar.update()
                ret.append({'info': data})
        return ret


if __name__ == "__main__":
    # statictic = Statistic(
    #     name='TCO19 SRM 752',
    #     standings_url='https://www.topcoder.com/stat?module=MatchList&nr=200&sr=1&c=round_overview&er=5&rd=17420',
    #     key='TCO19 SRM 752. 06.03.2019',
    #     start_time=datetime.strptime('06.03.2019', '%d.%m.%Y'),
    # )
    # pprint(statictic.get_standings(users=['tourist']))
    # pprint(statictic.get_standings())
    # pprint(Statistic.get_users_infos(['aropan']))
    # statictic = Statistic(
    #     name='SRM 767',
    #     standings_url='https://www.topcoder.com/stat?module=MatchList&c=round_overview&er=5&rd=17684',
    #     key='SRM 767. 18.09.2019',
    #     start_time=datetime.strptime('18.09.2019', '%d.%m.%Y'),
    # )
    # pprint(statictic.get_result())
    statictic = Statistic(
        name='Mathmania - Codefest 18',
        standings_url='https://www.topcoder.com/stat?module=MatchList&c=round_overview&er=5&rd=17259',
        key='Mathmania - Codefest 18. 01.09.2018',
        start_time=datetime.strptime('01.09.2018', '%d.%m.%Y'),
    )
    pprint(statictic.get_result('tourist'))
    # statictic = Statistic(
    #     name='Marathon Match Beta',
    #     standings_url='https://community.topcoder.com/longcontest/stats/?module=ViewOverview&rd=9874',
    #     key='Marathon Match Beta. 15.12.2005',
    #     start_time=datetime.strptime('15.12.2005', '%d.%m.%Y'),
    # )
    # statictic.get_standings()
    # statictic = Statistic(
    #     name='2',
    #     standings_url='https://community.topcoder.com/longcontest/stats/?module=ViewOverview&rd=9874',
    #     key='Marathon Match Beta. 15.12.2005',
    #     start_time=datetime.strptime('15.12.2005', '%d.%m.%Y'),
    # )
    # pprint(statictic.get_standings()['problems'])
