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
from urllib.parse import urlencode, urljoin, urlparse

import pytz

from clist.templatetags.extras import as_number, is_solved
from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.utils import create_upsolving_statistic
from utils.aes import AESModeOfOperation

API_KEYS = conf.CODEFORCES_API_KEYS
DEFAULT_API_KEY = API_KEYS[API_KEYS['__default__']]
SUBDOMAIN = ''


def api_query(
    method,
    params,
    api_key=DEFAULT_API_KEY,
    prev_time_queries={},
    api_url_format=f'https://{SUBDOMAIN}codeforces.com/api/%s'
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
            try:
                ret = json.loads(e.response)
            except json.decoder.JSONDecodeError:
                ret = {'status': str(e)}
            ret['code'] = e.code
        except json.decoder.JSONDecodeError as e:
            if attempt:
                sleep(1)
                continue
            ret = {'status': str(e)}
        break

    return ret


def _get(url, *args, return_url=False, **kwargs):
    if SUBDOMAIN and SUBDOMAIN not in url:
        url = url.replace('://codeforces.', '://%scodeforces.' % SUBDOMAIN, 1)
    page, last_url = REQ.get(url, *args, return_url=True, **kwargs)
    if 'document.cookie="RCPC="+toHex(slowAES.decrypt(c,2,a,b))+";' in page:
        matches = re.findall(r'(?P<var>[a-z]+)=toNumbers\("(?P<value>[^"]*)"\)', page)
        variables = {}
        for variable, value in matches:
            variables[variable] = [int(value[i:i + 2], 16) for i in range(0, len(value), 2)]

        size = len(variables['a'])
        ret = AESModeOfOperation().decrypt(variables['c'], None, 2, variables['a'], size, variables['b'])
        rcpc = ''.join(('0' if x < 16 else '') + hex(x)[2:] for x in map(ord, ret))
        REQ.add_cookie('RCPC', rcpc)

        result = re.search('document.location.href="(?P<url>[^"]*)"', page)
        url = result.group('url')
        page, last_url = REQ.get(url, *args, return_url=True, **kwargs)
        REQ.save_cookie()
    return (page, last_url) if return_url else page


class Statistic(BaseModule):
    OFFICIAL_PARTICIPANT_TYPES = {'CONTESTANT'}
    PARTICIPANT_TYPES = OFFICIAL_PARTICIPANT_TYPES | {'OUT_OF_COMPETITION'}
    SUBMISSION_URL_FORMAT_ = '{url}/submission/{sid}'
    PROBLEM_STATUS_URL_FORMAT_ = '/problemset/status/{cid}/problem/{short}'

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

    @staticmethod
    def process_submission(submission, result, upsolve, contest, binary):
        contest_url = contest.url.replace('contests', 'contest')

        info = {
            'submission_id': submission['id'],
            'url': Statistic.SUBMISSION_URL_FORMAT_.format(url=contest_url, sid=submission['id']),
            'external_solution': True,
        }

        if 'verdict' in submission:
            v = submission['verdict'].upper()
            info['verdict'] = ''.join(s[0].upper() for s in v.split('_')) if len(v) > 3 else v.upper()

        if 'programmingLanguage' in submission:
            info['language'] = submission['programmingLanguage']

        is_accepted = info.get('verdict') == 'OK'
        if not is_accepted and 'passedTestCount' in submission:
            info['test'] = submission['passedTestCount'] + 1

        party = submission['author']
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

            update_result = 'result' not in p or is_solved(p['result']) < is_accepted
            if (
                update_result or
                'submission_id' not in p or
                p['submission_id'] > info['submission_id'] and is_accepted
            ):
                p.update(info)
                if binary:
                    p['binary'] = binary
                if update_result:
                    p['result'] = '+' if is_accepted else '-1'
                info['updated'] = True
            r = as_number(p.get('result'), force=True)
            p['partial'] = not is_accepted and p.get('partial', True) and r and r > 0

        info['is_accepted'] = is_accepted
        return info

    def get_standings(self, users=None, statistics=None):

        def parse_points_info(points_info):
            if not points_info:
                return None
            return float(points_info.split('/')[0])

        if self.is_spectator_ranklist:
            return self.get_standings_from_html()

        contest_url = self.url.replace('contests', 'contest')
        standings_url = contest_url.rstrip('/') + '/standings'

        participant_types = self.PARTICIPANT_TYPES.copy()
        is_gym = '/gym/' in self.url
        if is_gym:
            participant_types.add('VIRTUAL')

        result = {}

        domain_users = {}
        if '_domain_users' in self.info:
            for user in self.info['_domain_users']:
                user = deepcopy(user)
                domain_users[user.pop('login')] = user

        problems_info = OrderedDict()
        all_special = True
        for unofficial in [True]:
            params = {
                'contestId': self.cid,
                'showUnofficial': str(unofficial).lower(),
            }
            if users:
                params['handles'] = ';'.join(users)

            data = api_query(method='contest.standings', params=params, api_key=self.api_key)

            if data['status'] != 'OK':
                if data.get('code') == 400:
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
                all_special = all_special and any('special' in tag for tag in (tags or []))
                d['url'] = urljoin(standings_url.rstrip('/'), f"problem/{d['short']}")

                if not is_gym and not users:
                    status_url = self.PROBLEM_STATUS_URL_FORMAT_.format(cid=self.cid, short=d['short'])
                    status_url = urljoin(self.url, status_url)
                    page = _get(status_url)
                    match = re.search(r'<div[^>]*>\s*(?:Problem|Задача)\s*(?P<code>[0-9A-Z]+)\s*-', page)
                    if match:
                        d['code'] = match.group('code')
                        if self.cid not in d['code']:
                            d['_no_problem_url'] = True

                problems_info[d['short']] = d

            grouped = any(
                'teamId' in row['party'] and row['party']['participantType'] in participant_types
                for row in data['result']['rows']
            )

            place = None
            last = None
            first_score = None
            last_score = None
            idx = 0
            teams_to_skip = set()
            for row in data['result']['rows']:
                party = row['party']

                is_ghost = row.get('ghost') or (is_gym and not party['members'])
                if is_ghost:
                    name = party['teamName']
                    party['members'] = [{
                        'handle': f'{name} {self.get_season()}',
                        'name': name,
                    }]

                for member in party['members']:
                    upsolve = party['participantType'] not in participant_types

                    handle = member['handle']

                    r = result.setdefault(handle, OrderedDict())

                    r['member'] = handle
                    if is_gym:
                        r['ghost'] = is_ghost
                    if 'room' in party:
                        r['room'] = as_number(party['room'])

                    r.setdefault('participant_type', []).append(party['participantType'])
                    r['_no_update_n_contests'] = not bool(participant_types & set(r['participant_type']))
                    r['_skip_medal'] = not bool(Statistic.OFFICIAL_PARTICIPANT_TYPES & set(r['participant_type']))

                    if is_ghost and member['name']:
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
                            new_points = parse_points_info(s['pointsInfo'])
                            if new_points is not None:
                                points = new_points

                        n = s.get('rejectedAttemptCount')
                        if n is not None and contest_type == 'ICPC' and points + n > 0:
                            points = f'+{"" if n == 0 else n}' if points > 0 else f'-{n}'

                        u = upsolve
                        if s['type'] == 'PRELIMINARY' and phase == 'SYSTEM_TEST':
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
                            new_points = parse_points_info(row['pointsInfo'])
                            if new_points is not None:
                                score = new_points

                        if is_gym:
                            r['place'] = row['rank']
                        elif unofficial:
                            if users:
                                r['place'] = '__unchanged__'
                            elif 'team_id' not in r and not (participant_types & set(r['participant_type'])):
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
                                if first_score is None:
                                    first_score = score
                                if score:
                                    last_score = score
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

        if not users:
            data = api_query(method='contest.ratingChanges', params=params, api_key=self.api_key)
            if data.get('status') not in ['OK', 'FAILED']:
                LOG.warning(f'Missing rating changes = {data}')
            if data and data.get('status') == 'OK':
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
        elif statistics:
            for handle, row in statistics.items():
                if handle not in result:
                    continue
                for field in ('old_rating', 'new_rating'):
                    if field in row:
                        r[field] = row[field]

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
            data = api_query('contest.status', params=params, api_key=self.api_key)
            if data.get('status') not in ['OK', 'FAILED']:
                raise ExceptionParseStandings(data)
            if data['status'] == 'OK':
                submissions.extend(data['result'])

        has_accepted = False
        for submission in submissions:
            party = submission['author']
            upsolve = party['participantType'] not in participant_types
            if (
                'relativeTimeSeconds' in submission
                and duration_seconds
                and duration_seconds < submission['relativeTimeSeconds']
            ):
                upsolve = True

            info = Statistic.process_submission(submission, result, upsolve, contest=self, binary=False)

            has_accepted |= info['is_accepted']
            if contest_type == 'IOI' and info['is_accepted']:
                k = submission['problem']['index']
                problems_info[k].setdefault('full_score', submission['points'])

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

        if (
            contest_type == 'IOI'
            and phase == 'FINISHED'
            and not has_accepted
            and all('full_score' not in problem for problem in problems_info.values())
        ):
            standings['default_problem_full_score'] = 'max' if first_score > last_score else 'min'

        if re.search('^educational codeforces round', self.name, re.IGNORECASE):
            standings['options'].setdefault('timeline', {}).update({'attempt_penalty': 10 * 60,
                                                                    'challenge_score': False})
        elif re.search(r'\<div\.\s*3\>', self.name, re.IGNORECASE):
            standings['options'].setdefault('timeline', {}).update({'attempt_penalty': 10 * 60,
                                                                    'challenge_score': False})

        now = datetime.utcnow().replace(tzinfo=pytz.utc)
        if (
            phase != 'FINISHED' and self.end_time + timedelta(hours=3) > now or
            abs(self.end_time - now) < timedelta(minutes=15)
        ):
            standings['timing_statistic_delta'] = timedelta(minutes=5)

        if grouped:
            standings['grouped_team'] = grouped

        if problems_info and all_special:
            standings['kind'] = 'special'

        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):
        assert resource is None or 'gym' not in resource.host

        handles = ';'.join(users)

        len_limit = 2000
        if len(handles) > len_limit:
            total_len = 0
            for i in range(len(users)):
                total_len += len(users[i])
                if total_len > len_limit:
                    return (
                        Statistic.get_users_infos(users[:i], pbar=pbar) +
                        Statistic.get_users_infos(users[i:], pbar=pbar)
                    )

        removed = []
        last_index = 0
        orig_users = list(users)
        for _ in range(len(users) * 2):
            handles = ';'.join(users)
            data = api_query(method='user.info', params={'handles': handles})
            if data['status'] == 'OK':
                break
            if data['status'] == 'FAILED' and data['comment'].startswith('handles: User with handle'):
                handle = data['comment'].split()[-3]
                location = REQ.geturl(f'https://codeforces.com/profile/{handle}')
                index = users.index(handle)
                if urlparse(location).path.rstrip('/'):
                    target = location.rstrip('/').split('/')[-1]
                    users[index] = target
                else:
                    removed.append((index, users[index]))
                    users.pop(index)
                if pbar is not None:
                    pbar.update(index - last_index)
                    last_index = index
            else:
                raise NameError(f'data = {data}')
        else:
            raise ValueError(f'Many failed query, data = {data}')

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
                data['name'] = ' '.join([data[f] for f in ['firstName', 'lastName'] if data.get(f)])
            ret.append({'info': data})
            if data and data['handle'] != orig:
                ret[-1]['rename'] = data['handle']
        return ret

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')
        page, last_url = _get(problem['url'], return_url=True)
        if last_url != problem['url']:
            raise ExceptionParseStandings('Not allowed to view source code')
        result = re.search('<pre[^>]*id="program-source-text"[^>]*class="(?P<class>[^"]*)"[^>]*>(?P<source>[^<]*)</pre>', page)  # noqa
        if not result:
            raise ExceptionParseStandings('Not found source code')
        solution = html.unescape(result.group('source'))
        ret = {'solution': solution}
        for c in result.group('class').split():
            if c.startswith('lang-'):
                ret['lang_class'] = c
        return ret

    @staticmethod
    def update_submissions(account, resource):
        info = deepcopy(account.info.setdefault('submissions_', {}))
        info.setdefault('count', 0)
        last_id = info.setdefault('last_id', -1)

        start = 1
        count = 10000 if last_id == -1 else 1000
        stop = False
        first_submission = True
        stats_caches = {}
        ret = {}
        while not stop:
            data = api_query(method='user.status', params={'handle': account.key, 'from': start, 'count': count})
            submissions = data['result']
            if not submissions:
                break

            for submission in submissions:
                if last_id >= submission['id']:
                    stop = True
                    break
                info['count'] += 1

                is_testing = submission.get('verdict', '').upper() == 'TESTING'
                if is_testing:
                    info = deepcopy(account.info.setdefault('submissions_', {}))
                    first_submission = True
                    continue

                if first_submission:
                    info['last_id'] = submission['id']
                    first_submission = False

                party = submission['author']
                participant_type = party['participantType']
                upsolve = participant_type not in Statistic.PARTICIPANT_TYPES
                if not upsolve:
                    continue

                contest_id = submission.get('contestId')
                if contest_id is None:
                    continue

                if contest_id in stats_caches:
                    contest, stat = stats_caches[contest_id]
                    created = False
                else:
                    contest = resource.contest_set.filter(key=contest_id).first()
                    if contest is None:
                        continue
                    stat, created = create_upsolving_statistic(contest=contest, account=account)
                    stats_caches[contest_id] = contest, stat

                if 'creationTimeSeconds' in submission:
                    submission_time = datetime.fromtimestamp(submission['creationTimeSeconds'])
                    submission_time = submission_time.replace(tzinfo=pytz.utc)
                    if not account.last_submission or account.last_submission < submission_time:
                        account.last_submission = submission_time

                addition = stat.addition
                if created:
                    participant_types = addition.setdefault('participant_type', [])
                    if participant_type not in participant_types:
                        participant_types.append(participant_type)

                result = {account.key: deepcopy(addition)}
                submission_info = Statistic.process_submission(submission, result,
                                                               upsolve=True, contest=contest, binary=True)
                if not submission_info.get('updated'):
                    continue

                ret.setdefault('n_updated', 0)
                ret['n_updated'] += 1

                stat.addition = result[account.key]
                stat.save()

            if len(submissions) < count:
                break
            start += count

        account.info['submissions_'] = info
        account.save(update_fields=['info', 'last_submission'])

        ret['n_contests'] = len(stats_caches)
        return ret


def run(*args):
    standings = Statistic(
        url='http://codeforces.com/group/u45n6JRJMl/contest/206201',
        key='206201:aropan',
        standings_url=None,
        info={}
    ).get_standings()
    pprint(standings)
