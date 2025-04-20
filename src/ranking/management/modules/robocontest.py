#!/usr/bin/env python3

import html
import json
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

import arrow
import tqdm
from django.db import transaction
from django.db.models import OuterRef
from ratelimiter import RateLimiter
from sql_util.utils import Exists

from clist.templatetags.extras import (as_number, get_problem_key, get_problem_name, get_problem_short, html_unescape,
                                       is_improved_solution, is_solved)
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse
from ranking.utils import create_upsolving_statistic


def process_submissions_page(resource, page):
    table = parsed_table.ParsedTable(page)
    for row in table:
        submission_id = int(row['#'].value)
        upsolving = bool(row[''].column.node.xpath('.//*[@title="Upsolve"]'))
        handle = row['User'].column.node.xpath('.//a/@href')[0].split('/')[-1]
        verdict = row['Status'].value
        task = html_unescape(row['Task'].value)
        is_accepted = verdict == 'Accepted'

        submission = {
            'handle': handle,
            'task_name': task,
            'upsolving': upsolving,
            'binary': is_accepted,
            'exec_time': row['Time'].value,
            'memory_usage': row['Memory'].value,
            'id': submission_id,
            'language': row['Language'].value,
            'submission_time': int(arrow.get(row['Sent date'].value,
                                             'DD.MM.YYYY HH:mm',
                                             tzinfo=resource.timezone).timestamp()),
        }

        if task_href := row['Task'].column.node.xpath('.//a/@href'):
            submission['task_id'] = task_href[0].rstrip('/').split('/')[-1]

        if match := re.search(r'(?P<verdict>[^(]*)\((?P<test>[^)]*)\)', verdict):
            verdict = match.group('verdict').strip()
            test = match.group('test').strip()
            if test.startswith('test'):
                submission['test'] = int(test[4:].strip())
        submission['verdict_full'] = verdict
        verdict_short = ''.join(w[0].upper() for w in verdict.split())
        submission['verdict'] = 'AC' if is_accepted else verdict_short

        yield submission


def process_submissions_url(resource, attempts_url, submissions_info, n_pages=-1):
    last_submission_id = submissions_info.setdefault('last_submission_id', -1)
    submissions_info.setdefault('count', 0)

    submissions_page = REQ.get(attempts_url)

    match = re.search('wire:snapshot="(?P<wire>[^"]*)"', submissions_page)
    snapshot = html_unescape(match.group('wire'))
    match = re.search('<meta name="csrf-token" content="(?P<token>[^"]*)">', submissions_page)
    csrf_token = match.group('token')

    progress_bar = tqdm.tqdm(desc='submissions fetching')
    while n_pages:
        n_pages -= 1
        n_processed = 0
        for submission in process_submissions_page(resource, submissions_page):
            if submission['id'] <= last_submission_id:
                return
            submissions_info['count'] += 1
            if submission['id'] > submissions_info['last_submission_id']:
                submissions_info['last_submission_id'] = submission['id']
                submissions_info['last_submission_time'] = arrow.get(submission['submission_time']).isoformat()
                submissions_info['time'] = arrow.now().isoformat()
            yield submission
            n_processed += 1
        progress_bar.update(n_processed)
        if not n_processed:
            return

        match = re.search(r'''setPage([^'"]*.(?P<page>[^,]*)['"],['"]page['"])[^>]*>\s*Next''', submissions_page)
        if not match:
            return
        set_page = match.group('page')

        component = {'snapshot': snapshot,
                     'updates': {},
                     'calls': [{'path': '', 'method': 'setPage', 'params': [set_page, 'page']}]}
        post_data = {'_token': csrf_token, 'components': [component]}
        post_data = json.dumps(post_data)

        data = REQ.get(
            'https://robocontest.uz/livewire/update',
            post=post_data,
            content_type='application/json',
            return_json=True,
        )
        component = data['components'][0]
        snapshot = component['snapshot']
        submissions_page = component['effects']['html']
    progress_bar.close()


def process_submission_problem(submission, upsolving, short, addition):
    problems = addition.setdefault('problems', {})
    problem = problems.setdefault(short, {})
    if upsolving:
        if is_solved(problem):
            return False
        problem = problem.setdefault('upsolving', {})
    if is_improved_solution(submission, problem):
        if 'result' in problem:
            submission.pop('binary')
        problem.update(submission)
        return True
    return False


def is_english_locale(page):
    match = re.search('<a[^>]*class="[^"]*font-weight-bold[^"]*"[^>]*>(?P<locale>[^<]+)</a>', page)
    return match.group('locale').lower().strip() == 'english'


def set_locale():
    return REQ.get('https://robocontest.uz/locale/en')


def get_page(*args, **kwargs):
    page, code = REQ.get(*args, return_code=True, **kwargs)
    page = page if code == 200 else None
    if page and not is_english_locale(page):
        page = set_locale()
        if not is_english_locale(page):
            raise ExceptionParseStandings('Failed to set locale')
    return page


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = self.url.rstrip('/') + '/results'

        problems_infos = OrderedDict()
        result = OrderedDict()

        n_page = 0
        n_skip = 0
        nothing = False
        progress_bar = tqdm.tqdm(desc='results pagination')
        while not nothing and n_skip < 5:
            n_page += 1
            page = get_page(standings_url + f'?page={n_page}')
            progress_bar.update()
            if page is None:
                n_skip += 1
                continue
            page = re.sub(r'<!(?:--)?\[[^\]]*\](?:--)?>', '', page)
            table = parsed_table.ParsedTable(page, as_list=True)
            nothing = True
            n_skip = 0

            for row in table:
                r = OrderedDict()

                for k, v in row:
                    f = k.strip().lower()
                    if f == '#':
                        if not v.value:
                            break
                        r['place'] = v.value
                    elif f.startswith('fullname'):
                        a = v.column.node.xpath('.//a')[0]
                        r['member'] = re.search('profile/(?P<key>[^/]+)', a.attrib['href']).group('key')
                        if a.text:
                            r['name'] = html.unescape(a.text).strip()
                        small = v.column.node.xpath('.//small')
                        if small and (text := small[0].text):
                            r['affiliation'] = html.unescape(text).strip()
                        if v.row.node.xpath('./*[contains(@class, "kicked")]'):
                            r['_no_update_n_contests'] = True
                        handle = r['member']
                        stats = (statistics or {}).get(handle, {})
                        problems = r.setdefault('problems', stats.get('problems', {}))
                    elif not f:
                        i = v.header.node.xpath('.//i')
                        if i:
                            c = i[0].attrib['class']
                            if 'strava' in c or 'chart-line' in c:
                                if v.value == '0':
                                    r['rating_change'] = 0
                                elif len(vs := v.value.lstrip('~').split()) == 2:
                                    new_rating, rating_change = map(int, vs)
                                    r['rating_change'] = rating_change
                                    r['new_rating'] = new_rating
                            elif 'tasks' in c:
                                r['tasks'] = v.value
                    elif f == 'ball':
                        r['solving'] = as_number(v.value)
                    elif f == 'penalty':
                        r['penalty'] = as_number(v.value)
                    elif len(f.split()[0]) == 1:
                        short, full_score = f.split()
                        short = short.title()
                        if short not in problems_infos:
                            name = html.unescape(v.header.node.attrib['title'])
                            problems_infos[short] = {
                                'short': short,
                                'name': name or short,
                                'url': urljoin(standings_url, v.header.node.xpath('.//a/@href')[0]),
                                'full_score': int(full_score),
                            }
                        if not v.value:
                            continue
                        val = v.value
                        p = problems.setdefault(short, {})
                        if val.startswith('+'):
                            p['result'], p['time'] = val.split()
                        elif val == '-':
                            p['result'] = '-1'
                        elif ' / ' in val:
                            res, full = [as_number(v) for v in val.split(' / ')]
                            if 0 < res < full:
                                p['partial'] = True
                            p['result'] = res
                        else:
                            p['result'] = val
                        if 'first-solved' in v.column.node.attrib['class']:
                            p['first_ac'] = True
                if not r.get('member'):
                    continue
                if not problems and not as_number(r['solving']):
                    continue
                if r.get('_no_update_n_contests'):
                    r.pop('place', None)
                result[r['member']] = r
                nothing = False
        progress_bar.close()

        contest_problems = list(problems_infos.values())
        for problem in tqdm.tqdm(contest_problems, desc='problems fetching'):
            problem_page = get_page(problem['url'], ignore_codes={403})
            if problem_page is None:
                continue
            match = re.search(r'<h[^>]*>\s*Task\s*#?(?P<key>[^<]*)</h', problem_page)
            problem['code'] = match.group('key').strip()
            archive_url = self.resource.problem_url.format(key=problem['code'])
            try:
                REQ.head(archive_url)
                problem['archive_url'] = archive_url
            except Exception:
                problem['archive_url'] = None

        problem_shorts = {p['name']: p['short'] for p in contest_problems}
        submissions_info = self.contest.submissions_info
        attempts_url = self.url.rstrip('/') + '/attempts'

        for submission in process_submissions_url(self.resource, attempts_url, submissions_info):
            task_name = submission.pop('task_name')
            submission.pop('task_id', None)
            handle = submission.pop('handle')
            upsolving = submission.pop('upsolving')

            if task_name not in problem_shorts:
                continue
            short = problem_shorts[task_name]

            created = handle not in result
            addition = result.setdefault(handle, {'member': handle, '_no_update_n_contests': True})
            if not process_submission_problem(submission, upsolving, short, addition) and created:
                result.pop(handle)

        ret = {
            'hidden_fields': ['affiliation'],
            'url': standings_url,
            'problems': contest_problems,
            'result': result,
            'submissions_info': submissions_info,
        }

        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_profile(handle):
            url = resource.profile_url.format(account=handle)
            try:
                page = get_page(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                raise e

            ret = {}
            match = re.search('<img[^>]*src="(?P<avatar>[^"]*)"[^>]*id="avatar"', page)
            if match:
                ret['avatar'] = urljoin(url, match.group('avatar'))

            for regex in (
                r'>(?P<val>[^<]*)</h[123]>\s*<p[^>]*>(?P<key>[^<]*)</p>',
                r'<th[^>]*>(?P<key>[^<]*)</th>\s*<td[^>]*>(?P<val>[^<]*)</td>',
            ):
                matches = re.finditer(regex, page)
                for match in matches:
                    key = match.group('key').strip().lower().replace(' ', '_')
                    val = html.unescape(match.group('val').strip())
                    ret[key] = val

            match = re.search(r'<h3[^>]*class="[^"]*card-title[^"]*"[^>]*>(?:\s*<[^>]*>)*(?P<name>[^<]*)', page)
            ret['name'] = html.unescape(match.group('name'))

            # for field in 'region', 'district':
            #     if ret.get(field):
            #         country = locator.get_country(ret[field], lang='ru')
            #         if country:
            #             ret['country'] = country
            #             break
            return ret

        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                ret = {'info': data}

                yield ret

    @transaction.atomic()
    @staticmethod
    def update_submissions(account, resource, **kwargs):
        profile_url = resource.profile_url.format(account=account.key)
        attempts_url = profile_url.rstrip('/') + '/attempts'

        contests_cache = {}
        statistics_cache = {}
        updated_info = defaultdict(int)

        def get_contest(key, name):
            cache_key = (key, name)
            if cache_key in contests_cache:
                return contests_cache[cache_key]
            if key:
                contests = resource.contest_set.filter(problem_set__key=key)
            else:
                contests = resource.contest_set.filter(problem_set__name=name)
                account_statistics = account.statistics_set.filter(contest=OuterRef('pk'))
                contests = contests.annotate(has_stat=Exists(account_statistics))
                contests = contests.order_by('-has_stat', 'start_time')
            contest = contests.first()
            contests_cache[cache_key] = contest
            return contest

        def get_statistic(contest):
            if contest not in statistics_cache:
                statistics_cache[contest], created = create_upsolving_statistic(
                    resource=resource, contest=contest, account=account)
            else:
                created = False
            return statistics_cache[contest], created

        for submission in process_submissions_url(resource, attempts_url, account.submissions_info):
            task_name = submission.pop('task_name')
            task_id = submission.pop('task_id', None)
            submission.pop('handle')
            upsolving = submission.pop('upsolving')

            if not task_id and (not task_name or task_name == '—'):
                updated_info['missing_tasks'] += 1
                continue

            contest = get_contest(task_id, task_name)
            if contest is None:
                updated_info['missing_contests'] += 1
                continue

            for problem in contest.problems_list:
                if get_problem_name(problem) == task_name:
                    break
                if task_id and get_problem_key(problem) == task_id:
                    break
            else:
                updated_info['missing_problems'] += 1
                continue

            submission_time = arrow.get(submission['submission_time']).datetime
            if account.last_submission is None or submission_time > account.last_submission:
                account.last_submission = submission_time

            short = get_problem_short(problem)
            statistic, created = get_statistic(contest)
            if process_submission_problem(submission, upsolving, short, statistic.addition):
                updated_info['n_updated'] += 1
                statistic.save()
            elif created:
                updated_info['n_removed_statistics'] += 1
                statistic.delete()
                statistics_cache.pop(contest)

        account.save(update_fields=['submissions_info', 'last_submission'])
        return updated_info
