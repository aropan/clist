# -*- coding: utf-8 -*-

import collections
import functools
import html
import json
import re
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import timedelta

import arrow
from django.utils.timezone import now
from first import first
from lazy_load import lz
from ratelimiter import RateLimiter
from tqdm import tqdm

from clist.templatetags.extras import as_number, get_problem_key, is_solved
from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse, ProxyLimitReached
from ranking.utils import clear_problems_fields, create_upsolving_statistic

eps = 1e-9
rate_limiter = RateLimiter(max_calls=4, period=1)


def create_req():
    req = REQ.duplicate()
    req.set_proxy(
        proxy=True,
        time_limit=10,
        n_limit=50,
        dump_proxy_filepath='sharedfiles/resource/atcoder/proxy',
        filepath_proxies='sharedfiles/resource/atcoder/proxies',
    )
    return req


req = lz(create_req)


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'
    RESULTS_URL_ = '{0.url}/results'
    SUBMISSIONS_URL_ = '{0.url}/submissions'
    TASKS_URL_ = '{0.url}/tasks'
    PROBLEM_URL_ = '{0.url}/tasks/{1}'
    SOLUTION_URL_ = '{0.url}/submissions/{1}'
    HISTORY_URL_ = '{0.scheme}://{0.netloc}/users/{1}/history'
    DEFAULT_LAST_SUBMISSION_TIME = -1
    DEFAULT_LAST_PAGE = 1
    KENKOOOO_SUBMISSIONS_URL_ = 'https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={}&from_second={}'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cid = self.key
        self._stop = None
        self._forbidden = None
        self._fetch_submissions_limit = 500

    @staticmethod
    def _get(*args, **kwargs):
        page = req.get(*args, raise_codes={404}, **kwargs)
        form = req.form(limit=2, page=page, selectors=['class="form-horizontal"'])
        if form:
            form['post'].update({
                'username': conf.ATCODER_HANDLE,
                'password': conf.ATCODER_PASSWORD,
            })
            page = req.get(form['url'], post=form['post'])
        return page

    def fetch_submissions(self, fuser=None, c_page=1):
        if self._fetch_submissions_limit is not None:
            if not self._fetch_submissions_limit:
                return
            self._fetch_submissions_limit -= 1

        url = self.SUBMISSIONS_URL_.format(self) + f'?page={c_page}'
        if fuser:
            url += f'&f.User={fuser}'

        codes = set()
        for attempt in range(4):
            if self._stop or self._forbidden:
                return

            with rate_limiter:
                try:
                    page = self._get(url)
                    break
                except FailOnGetResponse as e:
                    if e.code == 404:
                        return
                    codes.add(e.code)
                    time.sleep(attempt)
                except ProxyLimitReached:
                    return
        else:
            if 403 in codes:
                self._forbidden = True
            return

        regex = '<table[^>]*>.*?</table>'
        entry = re.search(regex, page, re.DOTALL)
        if entry:
            html_table = entry.group(0)
            table = parsed_table.ParsedTable(html_table, with_duplicate_colspan=True)
        else:
            table = []

        return url, page, table, c_page

    def _update_submissions(self, fusers, standings):
        result = standings['result']

        n_workers = 2
        with PoolExecutor(max_workers=n_workers) as executor:
            submissions = tqdm(executor.map(self.fetch_submissions, fusers),
                               total=len(fusers),
                               desc='gettings first page')

            for fuser, page_submissions in zip(fusers, submissions):
                if page_submissions is None:
                    break
                url, page, table, _ = page_submissions

                submissions_times = {}

                def process_page(url, page, table):
                    last_submission_time = 0
                    for r in table:
                        row = dict()
                        for k, v in list(r.items()):
                            if v.value == 'Detail':
                                href = first(v.column.node.xpath('.//a/@href'))
                                if href:
                                    row['url'] = urllib.parse.urljoin(url, href)
                                    row['external_solution'] = True
                            elif k == 'User':
                                row['name'] = v.value
                                href = v.column.node.xpath('.//a/@href')[0]
                                row['user'] = href.split('/')[-1]
                            else:
                                k = k.lower().replace(' ', '_')
                                row[k] = v.value

                        submission_time = arrow.get(row['submission_time'])
                        upsolve = submission_time >= self.end_time
                        row['submission_time'] = submission_time.timestamp()
                        last_submission_time = max(last_submission_time, row['submission_time'])

                        row['verdict'] = row.pop('status')
                        user = row.pop('user')
                        name = row.pop('name')
                        task = row.pop('task').split()[0]
                        score = float(row.pop('score'))

                        res = result.setdefault(user, collections.OrderedDict())
                        res.setdefault('member', user)
                        if name != user:
                            res['name'] = name
                        problems = res.setdefault('problems', {})
                        problem = problems.setdefault(task, {})
                        problem_score = problem.get('result', 0)

                        if upsolve:
                            problem = problem.setdefault('upsolving', {})
                            problem_score = problem.get('result', 0)
                            if 'submission_time' not in problem:
                                problem_score = 0
                        else:
                            seconds = int((submission_time - self.start_time).total_seconds())
                            row['time_in_seconds'] = seconds
                            row['time'] = f'{seconds // 60}:{seconds % 60:02d}'
                        st = submissions_times.setdefault((user, task, upsolve), problem.get('submission_time'))

                        if score > eps:
                            if (problem_score > score or (
                                problem_score == score
                                and 'submission_time' in problem
                                and row['submission_time'] > problem['submission_time']
                            )):
                                continue
                            row['result'] = score
                            problem.pop('submission_time', None)
                        elif problem_score > eps:
                            continue
                        elif problem_score < eps and (not st or st < row['submission_time']) and upsolve:
                            problem['result'] = problem_score - 1

                        if 'submission_time' in problem and row['submission_time'] <= problem['submission_time']:
                            continue

                        problem.update(row)
                    return last_submission_time

                last_submission_time = process_page(url, page, table)

                st_data = result.get(fuser, {}) if fuser else standings
                submissions_info = st_data.setdefault('_submissions_info', {})
                limit_st = submissions_info.pop('last_submission_time', self.DEFAULT_LAST_SUBMISSION_TIME)
                last_page = submissions_info.pop('last_page', self.DEFAULT_LAST_PAGE)
                last_page_st = submissions_info.pop('last_page_st', self.DEFAULT_LAST_SUBMISSION_TIME)
                c_page = last_page
                d_page = n_workers

                self._stop = False
                while not self._stop and not self._forbidden:
                    n_page = c_page + d_page
                    n_empty_tables = 0
                    fetch_submissions_user = functools.partial(self.fetch_submissions, fuser)

                    submissions_iter = executor.map(fetch_submissions_user, range(last_page + 1, n_page + 1))
                    if fuser is None:
                        submissions_iter = tqdm(submissions_iter, total=n_page - last_page,
                                                desc=f'getting submissions for ({last_page};{n_page}]')

                    for page_submissions in submissions_iter:
                        if page_submissions is None:
                            submissions_info['last_page'] = c_page
                            submissions_info['last_page_st'] = last_page_st
                            LOG.info(f'stopped after ({last_page};{c_page}] of {n_page}')
                            self._stop = True
                            break

                        url, page, table, c_page_ = page_submissions
                        submission_time = process_page(url, page, table)
                        last_page_st = max(last_page_st, submission_time)

                        if not table:
                            n_empty_tables += 1
                            if n_empty_tables >= n_workers:
                                self._stop = True
                                break
                        else:
                            c_page = c_page_
                            n_empty_tables = 0

                        if submission_time < limit_st:
                            self._stop = True
                            break
                    last_page = n_page
                    d_page *= 2
                if 'last_page' not in submissions_info:
                    submissions_info['last_submission_time'] = \
                        last_submission_time if last_page == self.DEFAULT_LAST_PAGE else last_page_st

    def get_standings(self, users=None, statistics=None, **kwargs):
        result = {}
        standings_url = self.standings_url or self.STANDING_URL_.format(self)

        fusers = []
        page = self._get(self.url)
        match = re.search(r'(?<=<li>)writer:.*?</?l[iu]>', page, re.I | re.DOTALL)
        writers = []
        if match:
            matches = re.findall('(?<=>)[^<]+(?=</)', match.group())
            writers = list()
            for m in matches:
                writers.extend(map(str.strip, re.split(r'[,\s]+', m)))
            writers = [w for w in writers if w and w != '?']

        url = f'{self.RESULTS_URL_.format(self)}/'
        try:
            page = self._get(url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e

        match = re.search(r'var\s*results\s*=\s*(\[[^\n]*\]);$', page, re.MULTILINE)
        data = json.loads(match.group(1))
        results = {}
        for row in data:
            if not row.get('IsRated'):
                continue
            handle = row.pop('UserScreenName')
            if users and handle not in users:
                continue
            if 'NewRating' not in row:
                continue
            r = collections.OrderedDict()
            for k in ['OldRating', 'NewRating', 'Performance']:
                if k in row:
                    r[k] = row[k]
            results[handle] = r

        try:
            page = self._get(f'{standings_url}/json')
            data = json.loads(page)
        except FailOnGetResponse as e:
            if e.code == 404:
                data = {}
            else:
                raise e

        if not data:
            try:
                standings_url = f'{self.STANDING_URL_.format(self)}/team'
                page = self._get(f'{standings_url}/json')
                data = json.loads(page)
            except FailOnGetResponse as e:
                if e.code == 404:
                    data = {}
                else:
                    raise e

        if not data:
            standings_url = self.url
            self._fetch_submissions_limit = None
            data = defaultdict(list)
            tasks = data.setdefault('TaskInfo', [])
            tasks_url = self.TASKS_URL_.format(self)
            page = self._get(tasks_url)
            table = parsed_table.ParsedTable(page)
            for r in table:
                short = r['']
                short = short[0].value if isinstance(short, list) else short.value
                name = r.get('問題名', r.get('Task Name'))
                url = first(name.column.node.xpath('.//a/@href'))
                url = urllib.parse.urljoin(tasks_url, url)
                url = url.rstrip('/')
                code = url.split('/')[-1]
                task = {
                    'TaskScreenName': code,
                    'Assignment': short,
                    'TaskName': name.value,
                }
                tasks.append(task)

        new_data = []
        teams = []
        handles = []
        for row in data['StandingsData']:
            if not row['IsTeam']:
                new_data.append(row)
                continue
            teams.append(row)
            handles.extend(row['Affiliation'].split(', '))
        if self.resource.account_set.filter(key__in=handles).exists():
            for row in teams:
                handles = row.pop('Affiliation').split(', ')
                row['team_id'] = row.pop('UserScreenName')
                row['_members'] = [{'account': m} for m in handles]
                for handle in handles:
                    r = deepcopy(row)
                    r['UserScreenName'] = handle
                    new_data.append(r)
        data['StandingsData'] = new_data

        task_info = collections.OrderedDict()
        for t in data['TaskInfo']:
            k = t['TaskScreenName']
            url = self.PROBLEM_URL_.format(self, k)
            task_info[k] = {
                'code': k,
                'short': t['Assignment'],
                'name': t['TaskName'] or k,
                'url': url,
            }

        info_problems = {get_problem_key(p): p for p in self.info.get('problems', [])}

        def get_problem_full_score(info):
            try:
                page = self._get(info['url'])
                match = re.search('<span[^>]*class="lang-[a-z]+"[^>]*>\s*(<script[^<]*>\s*</script>\s*)?<p>\s*(?:配点|Score)\s*(?:：|:)\s*<var>\s*(?P<score>[0-9]+)\s*</var>\s*(?:点|points)\s*</p>', page, re.I)  # noqa
                if match:
                    info['full_score'] = int(match.group('score'))
            except FailOnGetResponse as e:
                problem_key = get_problem_key(info)
                if problem_key in info_problems and 'full_score' in info_problems[problem_key]:
                    info['full_score'] = info_problems[problem_key]['full_score']
                    LOG.warning(f'Failed to get full score for {problem_key}'
                                f', using cached value = {info["full_score"]}')
                else:
                    raise e

        with PoolExecutor(max_workers=8) as executor:
            executor.map(get_problem_full_score, task_info.values())

        if any('full_score' not in t for t in task_info.values()):
            page = self._get(self.url)
            for match in re.finditer('<table[^>]*>.*</table>', page, re.MULTILINE | re.DOTALL):
                table = parsed_table.ParsedTable(match.group(0))
                header = [c.value for c in table.header.columns]
                if header != ['Task', 'Score']:
                    continue
                for row in table:
                    short = row['Task'].value
                    score = as_number(row['Score'].value, force=True)
                    tasks = [t for t in task_info.values() if t['short'] == short]
                    if len(tasks) == 1:
                        for t in tasks:
                            if 'full_score' not in t:
                                t['full_score'] = score

        has_rated = False
        has_new_rating = False

        for row in data['StandingsData']:
            if not row['TaskResults'] and not row.get('IsRated'):
                continue
            handle = row.pop('UserScreenName')
            if users is not None and handle not in users:
                continue
            r = result.setdefault(handle, collections.OrderedDict())
            account_info = r.setdefault('info', {})
            r['member'] = handle
            if (v := row.pop('UserIsDeleted', None)) is not None:
                account_info['deleted'] = v
            r['place'] = row.pop('Rank')
            total_result = row.pop('TotalResult')

            penalty = total_result['Elapsed'] // 10**9
            r['penalty'] = f'{penalty // 60}:{penalty % 60:02d}'

            r['solving'] = total_result['Score'] / 100.
            r['country'] = row.pop('Country')
            if 'UserName' in row:
                r['name'] = row.pop('UserName')

            stats = (statistics or {}).get(handle, {})
            problems = r.setdefault('problems', stats.get('problems', {}))
            clear_problems_fields(problems)
            solving = 0
            task_results = row.pop('TaskResults', {})
            for k, v in task_results.items():
                if 'Score' not in v:
                    continue
                letter = task_info[k]['short']
                p = problems.setdefault(letter, {})

                if v['Score'] > 0:
                    solving += 1

                    p['result'] = v['Score'] / 100.

                    seconds = v['Elapsed'] // 10**9
                    p['time_in_seconds'] = seconds
                    p['time'] = f'{seconds // 60}:{seconds % 60:02d}'

                    if v['Penalty'] > 0:
                        p['penalty'] = v['Penalty']
                else:
                    p_result = -v['Failure']
                    if p.get('result') != p_result:
                        p.pop('time', None)
                    p['result'] = p_result
            r['solved'] = {'solving': solving}
            r['IsTeam'] = row.pop('IsTeam')

            if 'team_id' in row:
                r['team_id'] = row.pop('team_id')
                r['_members'] = row.pop('_members')

            if r['IsTeam']:
                continue

            row.update(r)
            row.pop('Additional', None)
            if 'AtCoderRank' in row:
                row['AtcoderRank'] = row.pop('AtCoderRank')
            rating = row.pop('Rating', None)
            if rating is not None:
                account_info['rating'] = rating
            old_rating = row.pop('OldRating', None)

            for k, v in sorted(row.items()):
                r[k] = v

            if handle in results:
                r.update(results.pop(handle))

            if old_rating is not None and (old_rating or 'NewRating' in r):
                r['OldRating'] = old_rating

            if r.get('IsRated'):
                has_rated = True
                if r.get('NewRating') is not None:
                    has_new_rating = True

        try:
            url = f'{self.STANDING_URL_.format(self)}/virtual/json'
            page = self._get(url)
            data = json.loads(page)
        except FailOnGetResponse as e:
            if e.code == 404:
                data = {}
            else:
                raise e

        for row in data.get('StandingsData', []):
            if not row['TaskResults']:
                continue
            handle = row.pop('UserScreenName')
            if users is not None and handle not in users:
                continue
            r = result.setdefault(handle, collections.OrderedDict())
            account_info = r.setdefault('info', {})
            r['member'] = handle
            if (v := row.pop('UserIsDeleted', None)) is not None:
                account_info['deleted'] = v
            r['country'] = row.pop('Country')
            if 'UserName' in row:
                r['name'] = row.pop('UserName')

            stats = (statistics or {}).get(handle, {})
            problems = r.setdefault('problems', stats.get('problems', {}))
            clear_problems_fields(problems)
            task_results = row.pop('TaskResults', {})
            for k, v in task_results.items():
                if 'Score' not in v:
                    continue
                letter = task_info[k]['short']
                p = problems.setdefault(letter, {})
                p = p.setdefault('upsolving', {})
                p_result = p.get('result', 0)
                score = v['Score'] / 100.
                if score > 0 and score > p_result:
                    p['result'] = score

                    seconds = v['Elapsed'] // 10**9
                    p['time_in_seconds'] = seconds
                    p['time'] = f'{seconds // 60}:{seconds % 60:02d}'

                    if v['Penalty'] > 0:
                        p['penalty'] = v['Penalty']
                elif score <= 0 and p_result <= 0 and -v['Failure'] < p_result:
                    p['result'] = -v['Failure']
                    p.pop('time', None)

        if self.info.get('_submissions_info', {}).get('last_submission_time', -1) > 0:
            for r in result.values():
                problems = r.get('problems', {})
                if not problems:
                    continue
                no_url = False
                for p in problems.values():
                    u = p.get('upsolving', {})
                    if 'result' in p and 'url' not in p or 'result' in u and 'url' not in u:
                        no_url = True
                        break
                if no_url:
                    fusers.append(r['member'])

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(task_info.values()),
            'writers': writers,
        }

        if (
            has_rated
            and not has_new_rating
            and self.end_time < now() < self.end_time + timedelta(hours=3)
        ):
            standings['timing_statistic_delta'] = timedelta(minutes=30)

        if users or (users is None and now() < self.end_time + timedelta(days=30)):
            self._stop = False
            page_submissions = self.fetch_submissions()
            if page_submissions is not None:
                standings['_submissions_info'] = self.info.pop('_submissions_info', {}) if statistics else {}
                standings['info_fields'] = ['_submissions_info']

                if not users:
                    if fusers:
                        LOG.info(f'Numbers of users without urls for some problems: {len(fusers)}')
                    if not fusers or 'last_page' in standings['_submissions_info']:
                        fusers = [None]
                    elif len(fusers) > len(result) * 0.2:
                        standings['_submissions_info'].pop('_last_submission_time', None)
                        fusers = [None]

                self._update_submissions(fusers, standings)

            if page_submissions is not None and 'last_page' in standings['_submissions_info']:
                delta = timedelta(minutes=15)
                LOG.info(f'Repeat statistics update after {delta}')
                standings['timing_statistic_delta'] = delta

        for row in result.values():
            handle = row['member']
            row['url'] = self.SUBMISSIONS_URL_.format(self) + f'?f.User={handle}'
            has_result = any('result' in p for p in row.get('problems', {}).values())
            if has_result or row.get('IsRated'):
                row.pop('_no_update_n_contests', None)
            else:
                row['_no_update_n_contests'] = True

        standings['hidden_fields'] = [
            'Affiliation',
            'AtcoderRank',
            'Competitions',
            'IsRated',
            'IsTeam',
        ]
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        key_value_re = re.compile(
            r'''
            <tr>[^<]*<th[^>]*class="no-break"[^>]*>(?P<key>[^<]*)</th>[^<]*
            <td[^>]*>(?:\s*<[^>]*>)*(?P<value>[^<]+)
            ''',
            re.VERBOSE,
        )
        avatar_re = re.compile('''<img[^>]*class=["']avatar["'][^>]*src=["'](?P<url>[^"']*/icons/[^"']*)["'][^>]*>''')

        @rate_limiter
        def fetch_profile(user):
            url = resource.profile_url.format(account=user)
            try:
                page = Statistic._get(url)
            except FailOnGetResponse as e:
                if isinstance(e.args[0], UnicodeEncodeError):
                    return None
                code = e.code
                if code == 404:
                    return
                return {}
            ret = {}
            matches = key_value_re.finditer(page, re.VERBOSE)
            for match in matches:
                key = match.group('key').strip()
                value = match.group('value').strip()
                if value:
                    ret[key] = value
            match = avatar_re.search(page)
            if match:
                ret['avatar'] = match.group('url')
            if 'Rating' in ret:
                ret['rating'] = int(ret['Rating'])
            match = re.search('>var rating_history=(?P<rating_history>[^<]*);</', page)
            if match:
                contest_addition_update = {}
                rating_history = json.loads(match.group('rating_history'))
                for hist in rating_history:
                    url = hist['StandingsUrl']
                    match = re.search(r'/contests/(?P<contest_key>[^/]*)/', url)
                    if not match:
                        continue
                    contest_key = match.group('contest_key')
                    rank = hist['Place']
                    addition_update = {'_rank': rank}
                    if hist.get('NewRating'):
                        addition_update['new_rating'] = hist['NewRating']
                    if hist.get('OldRating'):
                        addition_update['old_rating'] = hist['OldRating']
                    if 'new_rating' in addition_update and 'old_rating' in addition_update:
                        addition_update['rating_change'] = addition_update['new_rating'] - addition_update['old_rating']
                    contest_addition_update[contest_key] = addition_update
                if contest_addition_update:
                    ret['_contest_addition_update_params'] = {
                        'update': contest_addition_update,
                        'try_renaming_check': True,
                    }
            return ret

        with PoolExecutor(max_workers=8) as executor:
            profiles = executor.map(fetch_profile, users)
            for data in profiles:
                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                else:
                    ret = {'info': data}
                    contest_addition_update_params = data.pop('_contest_addition_update_params', None)
                    if contest_addition_update_params:
                        ret['contest_addition_update_params'] = contest_addition_update_params
                    yield ret
                pbar.update()

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')

        page = Statistic._get(problem['url'])
        match = re.search('<pre[^>]*id="submission-code"[^>]*>(?P<source>[^<]*)</pre>', page)
        if not match:
            raise ExceptionParseStandings('Not found source code')
        solution = html.unescape(match.group('source'))
        return {'solution': solution}

    @staticmethod
    def update_submissions(account, resource, **kwargs):
        info = deepcopy(account.info.setdefault('submissions_', {}))
        info.setdefault('count', 0)
        last_from_seconds = info.setdefault('last_from_seconds', -1)

        @RateLimiter(max_calls=1, period=1)
        def fetch_submissions(url):
            submissions = json.loads(REQ.get(url))
            return submissions

        stop = False
        stats_caches = {}
        ret = {}
        while not stop:
            url = Statistic.KENKOOOO_SUBMISSIONS_URL_.format(account.key, last_from_seconds + 1)
            submissions = fetch_submissions(url)
            new_submissions = False

            for submission in submissions:
                info['count'] += 1

                if submission['epoch_second'] > last_from_seconds:
                    last_from_seconds = submission['epoch_second']
                    new_submissions = True

                contest_id = submission.pop('contest_id')
                if contest_id is None:
                    continue

                if contest_id in stats_caches:
                    contest, stat = stats_caches[contest_id]
                else:
                    contest = resource.contest_set.filter(key=contest_id).first()
                    if contest is None:
                        continue
                    stat, _ = create_upsolving_statistic(resource=resource, contest=contest, account=account)
                    stats_caches[contest_id] = contest, stat

                problem_id = submission.pop('problem_id')

                for problem in contest.info.get('problems', []):
                    if problem['code'].lower() == problem_id.lower():
                        break
                else:
                    problem = None

                if problem is None:
                    LOG.warning(f'Missing problem: contest = {contest}, account = {account}, problem = {problem_id}')
                    continue

                short = problem['short']

                problems = stat.addition.setdefault('problems', {})
                problem = problems.setdefault(short, {})
                if is_solved(problem):
                    continue

                submission_time = arrow.get(submission['epoch_second'])
                upsolve = submission_time >= contest.end_time
                if not upsolve:
                    continue

                upsolving = problem.get('upsolving', {})

                if is_solved(upsolving):
                    continue

                problem_info = {
                    'url': Statistic.SOLUTION_URL_.format(contest, submission['id']),
                    'result': as_number(submission.pop('point')),
                }
                for key, field in (
                    ('result', 'verdict'),
                    ('length', 'code_size'),
                    ('execution_time', 'exec_time'),
                    ('epoch_second', 'submission_time'),
                    ('language', 'language'),
                ):
                    problem_info[field] = submission.pop(key)

                problem_score = problem.get('result', 0)
                if (
                    (problem_score, problem.get('submission_time', 0)) >=
                    (problem_info['result'], problem_info['submission_time'])
                ):
                    continue

                if problem_score < eps and problem_info['result'] < eps:
                    problem_info['result'] = problem_score - 1
                elif (
                    problem_score == problem_info['result'] and
                    'submission_time' in problem and problem['submission_time'] < problem_info['submission_time']
                ):
                    continue

                problem['upsolving'] = problem_info

                if not account.last_submission or account.last_submission < submission_time:
                    account.last_submission = submission_time.datetime

                ret.setdefault('n_updated', 0)
                ret['n_updated'] += 1

                stat.save()

            if not new_submissions:
                break

        info['last_from_seconds'] = last_from_seconds
        account.info['submissions_'] = info
        account.save(update_fields=['info', 'last_submission'])

        ret['n_contests'] = len(stats_caches)
        return ret
