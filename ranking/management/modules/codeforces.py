# -*- coding: utf-8 -*-

import html
import json
import re
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha512
from pprint import pprint
from random import choice
from string import ascii_lowercase
from time import sleep, time
from urllib.parse import urlencode, urljoin

import pytz

from clist.templatetags.extras import as_number
from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from utils.aes import AESModeOfOperation

API_KEYS = conf.CODEFORCES_API_KEYS
DEFAULT_API_KEY = API_KEYS[API_KEYS['__default__']]


def _query(
    method,
    params,
    api_key=DEFAULT_API_KEY,
    prev_time_queries={},
    api_url_format='https://codeforces.com/api/%s'
):
    url = api_url_format % method
    key, secret = api_key
    params = dict(params)

    params.update({
        'time': int(time()),
        'apiKey': key,
        'lang': 'en',
    })

    url_encode = '&'.join(('%s=%s' % (k, v) for k, v in sorted(params.items())))

    api_sig_prefix = ''.join(choice(ascii_lowercase) for x in range(6))
    api_sig = '%s/%s?%s#%s' % (
        api_sig_prefix,
        method,
        url_encode,
        secret,
    )
    params['apiSig'] = api_sig_prefix + sha512(api_sig.encode('utf8')).hexdigest()
    url += '?' + urlencode(params)

    times = prev_time_queries.setdefault((key, secret), [])
    if len(times) == 5:
        delta = max(4 - (time() - times[0]), 0)
        sleep(delta)
        times.clear()

    md5_file_cache = url
    for k in ('apiSig', 'time', ):
        md5_file_cache = re.sub('%s=[0-9a-z]+' % k, '', md5_file_cache)
    times.append(time())

    for attempt in reversed(range(5)):
        try:
            page = REQ.get(url, md5_file_cache=md5_file_cache)
            times[-1] = time()
            ret = json.loads(page)
        except FailOnGetResponse as e:
            if e.code == 503 and attempt:
                sleep(1)
                continue
            err = e.args[0]
            if hasattr(err, 'fp'):
                try:
                    ret = json.load(err.fp)
                except json.decoder.JSONDecodeError:
                    ret = {'status': str(e)}
            else:
                ret = {'status': str(e)}
            ret['code'] = getattr(err, 'code', None)
        break

    return ret


def _get(url, *args, **kwargs):
    page = REQ.get(url, *args, **kwargs)
    if 'document.cookie="RCPC="+toHex(slowAES.decrypt(c,2,a,b))+";' in page:
        matches = re.findall(r'(?P<var>[a-z]+)=toNumbers\("(?P<value>[^"]*)"\)', page)
        variables = {}
        for variable, value in matches:
            variables[variable] = [int(value[i:i + 2], 16) for i in range(0, len(value), 2)]

        size = len(variables['a'])
        ret = AESModeOfOperation().decrypt(variables['c'], None, 2, variables['a'], size, variables['b'])
        rcpc = ''.join(('0' if x < 16 else '') + hex(x)[2:] for x in map(ord, ret))
        REQ.add_cookie('RCPC', rcpc)

        match = re.search('document.location.href="(?P<url>[^"]*)"', page)
        url = match.group('url')
        page = REQ.get(url, *args, **kwargs)
        REQ.save_cookie()
    return page


class Statistic(BaseModule):
    PARTICIPANT_TYPES = ['CONTESTANT', 'OUT_OF_COMPETITION']
    SUBMISSION_URL_FORMAT_ = '{url}/submission/{sid}'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.is_spectator_ranklist = self.standings_url and 'spectator/ranklist' in self.standings_url
        if self.is_spectator_ranklist:
            return

        cid = self.key
        if ':' in cid:
            cid, api = cid.split(':', 1)
            self.api_key = api.split(':') if ':' in api else API_KEYS[api]
        else:
            self.api_key = DEFAULT_API_KEY
        if not re.match('^[0-9]+$', cid):
            raise InitModuleException(f'Contest id {cid} should be number')
        self.cid = cid

    def get_standings_from_html(self):
        url = urljoin(self.standings_url, '?lang=en')
        page = REQ.get(url)
        regex = '''<table[^>]*standings[^>]*>.*?</table>'''
        match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        mapping = {
            '#': 'place',
            'Who': 'name',
            '=': 'solving',
            'Penalty': 'penalty',
        }
        table = parsed_table.ParsedTable(html_table, header_mapping=mapping)

        season = self.get_season()

        problems_info = OrderedDict()
        result = {}
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in r.items():
                if len(k) == 1:
                    problems_info.setdefault(k, {'short': k})
                    if v.value:
                        p = problems.setdefault(k, {})
                        v = v.value
                        if ' ' in v:
                            v, p['time'] = v.split()
                        p['result'] = v
                elif k == 'name':
                    f = v.column.node.xpath('.//img[@class="standings-flag"]/@title')
                    if f:
                        row['country'] = f[0]
                    a = v.column.node.xpath('.//a')
                    if not a:
                        row[k] = v.value
                        row['member'] = row['name'] + ' ' + season
                    else:
                        for el in a:
                            href = el.attrib.get('href')
                            if not href:
                                continue
                            key, val = href.strip('/').split('/')
                            if key == 'team':
                                row['name'] = el.text
                                row['team_id'] = val
                                row['_account_url'] = urljoin(url, href)
                            elif key == 'profile':
                                row.setdefault('members', []).append(val)
                elif v.value:
                    if k == 'penalty':
                        row[k] = int(v.value)
                    elif v.value:
                        row[k] = v.value

            if 'solving' not in row:
                continue

            if 'members' in row:
                if 'team_id' in row:
                    row['_members'] = [{'account': m} for m in row['members']]
                for member in row.pop('members'):
                    result[member] = deepcopy(row)
                    result[member]['member'] = member
            else:
                result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings

    def get_standings(self, users=None, statistics=None):

        if self.is_spectator_ranklist:
            return self.get_standings_from_html()

        contest_url = self.url.replace('contests', 'contest')
        standings_url = contest_url.rstrip('/') + '/standings'

        is_gym = '/gym/' in self.url
        result = {}

        domain_users = {}
        if '_domain_users' in self.info:
            for user in self.info['_domain_users']:
                user = deepcopy(user)
                domain_users[user.pop('login')] = user

        problems_info = OrderedDict()
        for unofficial in [True]:
            params = {
                'contestId': self.cid,
                'showUnofficial': str(unofficial).lower(),
            }
            if users:
                params['handles'] = ';'.join(users)

            data = _query(method='contest.standings', params=params, api_key=self.api_key)

            if data['status'] != 'OK':
                if data['code'] == 400:
                    return {'action': 'delete'}
                raise ExceptionParseStandings(data['status'])

            phase = data['result']['contest'].get('phase', 'FINISHED').upper()
            contest_type = data['result']['contest']['type'].upper()
            duration_seconds = data['result']['contest'].get('durationSeconds')

            result_problems = data['result']['problems']
            for p in result_problems:
                d = {'short': p['index'], 'name': p['name']}
                if 'points' in p:
                    d['full_score'] = p['points']
                tags = p.get('tags')
                if tags:
                    d['tags'] = tags
                d['url'] = urljoin(standings_url.rstrip('/'), f"problem/{d['short']}")

                problems_info[d['short']] = d

            if users is not None and not users:
                continue

            grouped = any('teamId' in row['party'] for row in data['result']['rows'])
            if grouped:
                grouped = all(
                    'teamId' in row['party'] or row['party']['participantType'] not in self.PARTICIPANT_TYPES
                    for row in data['result']['rows']
                )

            place = None
            last = None
            idx = 0
            teams_to_skip = set()
            for row in data['result']['rows']:
                party = row['party']

                if is_gym and not party['members']:
                    is_ghost_team = True
                    name = party['teamName']
                    party['members'] = [{
                        'handle': f'{name} {self.get_season()}',
                        'name': name,
                    }]
                else:
                    is_ghost_team = False

                for member in party['members']:
                    if is_gym:
                        upsolve = False
                    else:
                        upsolve = party['participantType'] not in self.PARTICIPANT_TYPES

                    handle = member['handle']

                    r = result.setdefault(handle, OrderedDict())

                    r['member'] = handle
                    if 'room' in party:
                        r['room'] = as_number(party['room'])

                    r.setdefault('participant_type', []).append(party['participantType'])
                    r['_no_update_n_contests'] = 'CONTESTANT' not in r['participant_type']

                    if is_ghost_team and member['name']:
                        r['name'] = member['name']
                        r['_no_update_name'] = True
                    elif grouped and (not upsolve and not is_gym or 'name' not in r):
                        r['name'] = ', '.join(m['handle'] for m in party['members'])
                        if 'teamId' in party:
                            r['team_id'] = party['teamId']
                            r['name'] = f"{party['teamName']}"
                            r['_members'] = [{'account': m['handle']} for m in party['members']]
                            r['_account_url'] = urljoin(self.url, '/team/' + str(r['team_id']))
                        r['_no_update_name'] = True
                    if domain_users and '=' in handle:
                        _, login = handle.split('=', 1)
                        r.update(domain_users.get(login, {}))

                    hack = row['successfulHackCount']
                    unhack = row['unsuccessfulHackCount']

                    problems = r.setdefault('problems', {})
                    for i, s in enumerate(row['problemResults']):

                        k = result_problems[i]['index']
                        points = float(s['points'])
                        if contest_type == 'IOI' and 'pointsInfo' in s:
                            points = float(s['pointsInfo'] or '0')

                        n = s.get('rejectedAttemptCount')
                        if n is not None and contest_type == 'ICPC' and points + n > 0:
                            points = f'+{"" if n == 0 else n}' if points > 0 else f'-{n}'

                        u = upsolve
                        if s['type'] == 'PRELIMINARY':
                            p = {'result': f'?{n + 1}'}
                        elif points or n:
                            if not points:
                                points = f'-{n}'
                                n = None
                            p = {'result': points}
                            if contest_type == 'IOI':
                                full_score = problems_info[k].get('full_score')
                                if full_score:
                                    p['partial'] = points < full_score
                            elif contest_type == 'CF' and n:
                                p['penalty_score'] = n
                        else:
                            continue

                        if 'bestSubmissionTimeSeconds' in s and duration_seconds:
                            time = s['bestSubmissionTimeSeconds']
                            if time > duration_seconds:
                                u = True
                            else:
                                p['time_in_seconds'] = time
                                time /= 60
                                p['time'] = '%02d:%02d' % (time / 60, time % 60)
                        a = problems.setdefault(k, {})
                        if u:
                            a['upsolving'] = p
                        else:
                            a.update(p)

                    if row['rank'] and not upsolve:
                        score = row['points']
                        if contest_type == 'IOI' and 'pointsInfo' in row:
                            score = float(row['pointsInfo'] or '0')

                        if is_gym:
                            r['place'] = row['rank']
                        elif unofficial:
                            if users:
                                r['place'] = '__unchanged__'
                            elif 'team_id' not in r and 'OUT_OF_COMPETITION' in r.get('participant_type', []):
                                r['place'] = None
                            else:
                                if 'team_id' in r:
                                    if r['team_id'] not in teams_to_skip:
                                        teams_to_skip.add(r['team_id'])
                                        idx += 1
                                else:
                                    idx += 1
                                value = (score, row.get('penalty'))
                                if last != value:
                                    last = value
                                    place = idx
                                r['place'] = place

                        r['solving'] = score
                        if contest_type == 'ICPC':
                            r['penalty'] = row['penalty']

                    if hack or unhack:
                        r['hack'] = {
                            'title': 'hacks',
                            'successful': hack,
                            'unsuccessful': unhack,
                        }

        params.pop('showUnofficial')

        data = _query(method='contest.ratingChanges', params=params, api_key=self.api_key)
        if data.get('status') not in ['OK', 'FAILED']:
            raise ExceptionParseStandings(data)
        if data and data['status'] == 'OK':
            for row in data['result']:
                if str(row.pop('contestId')) != self.key:
                    continue
                handle = row.pop('handle')
                if handle not in result:
                    continue
                r = result[handle]
                old_rating = row.pop('oldRating')
                new_rating = row.pop('newRating')
                r['old_rating'] = old_rating
                r['new_rating'] = new_rating

        params = {'contestId': self.cid}
        if users:
            array_params = []
            for user in users:
                params['handle'] = user
                array_params.append(deepcopy(params))
        else:
            array_params = [params]

        submissions = []
        for params in array_params:
            data = _query('contest.status', params=params, api_key=self.api_key)
            if data.get('status') not in ['OK', 'FAILED']:
                raise ExceptionParseStandings(data)
            if data['status'] == 'OK':
                submissions.extend(data['result'])

        for submission in submissions:
            party = submission['author']

            info = {
                'submission_id': submission['id'],
                'url': Statistic.SUBMISSION_URL_FORMAT_.format(url=contest_url, sid=submission['id']),
                'external_solution': True,
            }

            if 'verdict' in submission:
                v = submission['verdict'].upper()
                if v == 'PARTIAL':
                    info['partial'] = True
                info['verdict'] = ''.join(s[0].upper() for s in v.split('_')) if len(v) > 3 else v.upper()

            if 'programmingLanguage' in submission:
                info['language'] = submission['programmingLanguage']

            is_accepted = info.get('verdict') == 'OK'
            if not is_accepted and 'passedTestCount' in submission:
                info['test'] = submission['passedTestCount'] + 1

            if is_gym:
                upsolve = False
            else:
                upsolve = party['participantType'] not in self.PARTICIPANT_TYPES

            if (
                'relativeTimeSeconds' in submission
                and duration_seconds
                and duration_seconds < submission['relativeTimeSeconds']
            ):
                upsolve = True

            for member in party['members']:
                handle = member['handle']
                if handle not in result:
                    continue
                r = result[handle]
                problems = r.setdefault('problems', {})
                k = submission['problem']['index']
                p = problems.setdefault(k, {})
                if upsolve:
                    p = p.setdefault('upsolving', {})
                if 'submission_id' not in p:
                    p.update(info)
                    if 'result' not in p:
                        p['result'] = '+' if is_accepted else '-1'
                elif upsolve:
                    v = str(p.get('result'))
                    if v and v[0] in ['-', '+']:
                        v = 0 if v == '+' else int(v)
                        v = v + 1 if v >= 0 else v - 1
                        p['result'] = f'{"+" if v > 0 else ""}{v}'

        result = {
            k: v for k, v in result.items()
            if v.get('hack') or v.get('problems') or 'new_rating' in v or not v.get('_no_update_n_contests')
        }

        def to_score(x):
            return (
                (1 if x.startswith('+') or not x.startswith('?') and float(x) > 0 else 0)
                if isinstance(x, str) else x
            )

        def to_solve(x):
            return not x.get('partial', False) and to_score(x.get('result', 0)) > 0

        for r in result.values():
            upsolving = 0
            solving = 0
            upsolving_score = 0

            for a in r['problems'].values():
                if 'upsolving' in a and to_solve(a['upsolving']) > to_solve(a):
                    upsolving_score += to_score(a['upsolving']['result'])
                    upsolving += to_solve(a['upsolving'])
                else:
                    solving += to_solve(a)
            r.setdefault('solving', 0)
            r['upsolving'] = upsolving_score
            if abs(solving - r['solving']) > 1e-9 or abs(upsolving - r['upsolving']) > 1e-9:
                r['solved'] = {
                    'solving': solving,
                    'upsolving': upsolving,
                }

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
            'options': {
                'fixed_fields': [('hack', 'Hacks')],
            },
        }

        if re.search('^educational codeforces round', self.name, re.IGNORECASE):
            standings['options'].setdefault('timeline', {}).update({'attempt_penalty': 10 * 60,
                                                                    'challenge_score': False})

        if phase != 'FINISHED' and self.end_time + timedelta(hours=3) > datetime.utcnow().replace(tzinfo=pytz.utc):
            standings['timing_statistic_delta'] = timedelta(minutes=3)
        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):
        handles = ';'.join(users)

        len_limit = 1000
        if len(handles) > len_limit:
            s = 0
            for i in range(len(users)):
                s += len(users[i])
                if s > len_limit:
                    return Statistic.get_users_infos(users[:i], pbar) + Statistic.get_users_infos(users[i:], pbar)

        removed = []
        last_index = 0
        orig_users = list(users)
        while True:
            handles = ';'.join(users)
            data = _query(method='user.info', params={'handles': handles})
            if data['status'] == 'OK':
                break
            if data['status'] == 'FAILED' and data['comment'].startswith('handles: User with handle'):
                handle = data['comment'].split()[-3]
                location = REQ.geturl(f'https://codeforces.com/profile/{handle}')
                index = users.index(handle)
                if location.endswith('//codeforces.com/'):
                    removed.append((index, users[index]))
                    users.pop(index)
                else:
                    target = location.rstrip('/').split('/')[-1]
                    users[index] = target
                if pbar is not None:
                    pbar.update(index - last_index)
                    last_index = index
            else:
                raise NameError(f'data = {data}')
        if pbar is not None:
            pbar.update(len(users) - last_index)

        infos = data['result']
        for index, user in removed:
            infos.insert(index, None)
            users.insert(index, user)

        ret = []
        assert len(infos) == len(users)
        for data, user, orig in zip(infos, users, orig_users):
            if data:
                if data['handle'].lower() != user.lower():
                    raise ValueError(f'Do not match handle name for user = {user} and data = {data}')
                if data.get('avatar', '').endswith('/no-avatar.jpg'):
                    data.pop('avatar')
                if data.get('titlePhoto', '').endswith('/no-title.jpg'):
                    data.pop('titlePhoto')
            ret.append({'info': data})
            if data and data['handle'] != orig:
                ret[-1]['rename'] = data['handle']
        return ret

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')

        page = _get(problem['url'])
        match = re.search('<pre[^>]*id="program-source-text"[^>]*class="(?P<class>[^"]*)"[^>]*>(?P<source>[^<]*)</pre>', page)  # noqa
        if not match:
            raise ExceptionParseStandings('Not found source code')
        solution = html.unescape(match.group('source'))
        ret = {'solution': solution}
        for c in match.group('class').split():
            if c.startswith('lang-'):
                ret['lang_class'] = c
        return ret


def run(*args):
    standings = Statistic(
        url='http://codeforces.com/group/u45n6JRJMl/contest/206201',
        key='206201:aropan',
        standings_url=None,
        info={}
    ).get_standings()
    pprint(standings)
