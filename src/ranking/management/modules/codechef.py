#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import json
import re
import sys
import time
import traceback
from collections import OrderedDict, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from functools import partial
from urllib.parse import quote, urljoin

import arrow
import requests
import tqdm
from django.db import transaction
from django.db.models import Q
from first import first
from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number, get_item, is_improved_solution, slug
from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.utils import clear_problems_fields, create_upsolving_statistic
from utils.timetools import parse_datetime


class Statistic(BaseModule):
    STANDINGS_URL_FORMAT_ = 'https://www.codechef.com/rankings/{key}'
    API_CONTEST_URL_FORMAT_ = 'https://www.codechef.com/api/contests/{key}'
    API_RANKING_URL_FORMAT_ = 'https://www.codechef.com/api/rankings/{key}?sortBy=rank&order=asc&page={page}&itemsPerPage={per_page}'  # noqa
    API_PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/api/contests/{key}/problems/{code}'
    PROFILE_URL_FORMAT_ = 'https://www.codechef.com/users/{user}'
    PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/problems/{code}'
    CONTEST_PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/{key}/problems/{code}'
    TEAM_URL_FORMAT_ = 'https://www.codechef.com/teams/view/{user}'
    SUBMISSIONS_URL_ = 'https://www.codechef.com/recent/user?page={page}&user_handle={user}'
    E429_TIMEOUT = None
    E429_DELAY = timedelta(seconds=60)

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self._username = conf.CODECHEF_USERNAME
        self._password = conf.CODECHEF_PASSWORD

    @staticmethod
    def _get_headers_with_csrf_token(key):
        standings_url = Statistic.STANDINGS_URL_FORMAT_.format(key=key)
        page = REQ.get(standings_url)
        for regex in (
            r'window.csrfToken\s*=\s*"([^"]*)"',
            '<input[^>]*name="csrfToken"[^>]*id="edit-csrfToken"[^>]*value="([^"]*)"',
        ):
            match = re.search(regex, page)
            if match:
                csrf_token = match.group(1)
                return {'x-csrf-token': csrf_token, 'x-requested-with': 'XMLHttpRequest'}

    @RateLimiter(max_calls=1, period=1)
    @staticmethod
    def _get(*args, proxy=None, **kwargs):
        now = datetime.now()
        if proxy is None or Statistic.E429_TIMEOUT is None or Statistic.E429_TIMEOUT < now:
            additional_attempts = kwargs.setdefault('additional_attempts', {})
            additional_attempts[429] = {'count': 1}
            kwargs.setdefault('additional_delay', 2)
            try:
                return REQ.get(*args, **kwargs)
            except FailOnGetResponse as e:
                if e.code != 429 or proxy is None:
                    raise e
            Statistic.E429_TIMEOUT = now + Statistic.E429_DELAY
            kwargs.pop('additional_attempts')
            return Statistic._get(*args, proxy=proxy, **kwargs)
        else:
            kwargs.setdefault('n_attempts', 20)
            return proxy.get(*args, **kwargs)

    def get_standings(self, users=None, statistics=None, **kwargs):
        # REQ.get('https://www.codechef.com/')

        # try:
        #     form = REQ.form()
        #     form['post'].update({
        #         'name': self._username,
        #         'pass': self._password,
        #     })
        #     page = REQ.get(form['url'], post=form['post'])

        #     form = REQ.form()
        #     if form['url'] == '/session/limit':
        #         for field in form['unchecked'][:-1]:
        #             form['post'][field['name']] = field['value'].encode('utf8')
        #         page = REQ.get(form['url'], post=form['post'])
        # except Exception:
        #     pass

        url = self.API_CONTEST_URL_FORMAT_.format(**self.__dict__)
        page = REQ.get(url)
        data = json.loads(page)
        if data['status'] != 'success':
            raise ExceptionParseStandings(json.dumps(data))

        is_frozen = data.get('isRanklistFrozen')
        if 'child_contests' in data:
            contest_infos = {
                d['contest_code']: {'division': k}
                for k, d in data['child_contests'].items()
            }
        else:
            contest_infos = {self.key: {}}

        options = {}

        rules = data.get('rules')
        attempt_penalty = 10 * 60
        if rules:
            match = re.search(r'(?P<penalty>[0-9]+)(?:\s*<[^>]*>)?\s*penalty\s*minute', rules, re.I)
            if match:
                attempt_penalty = int(match.group('penalty')) * 60
                options.setdefault('timeline', {}).update({'attempt_penalty': attempt_penalty})

        result = {}

        problems_info = dict() if len(contest_infos) > 1 else list()
        hidden_fields = set()
        problems_data = defaultdict(dict)
        writers = defaultdict(int)

        for key, contest_info in contest_infos.items():
            headers = Statistic._get_headers_with_csrf_token(key)
            if not headers:
                raise ExceptionParseStandings('not found csrf token')

            n_page = 0
            per_page = 150
            n_total_page = None
            pbar = None
            ranking_type = None
            problem_infos = {}
            to_update_partial = []
            while n_total_page is None or n_page < n_total_page:
                n_page += 1
                time.sleep(2)
                url = self.API_RANKING_URL_FORMAT_.format(key=key, page=n_page, per_page=per_page)

                if users:
                    urls = [f'{url}&search={user}' for user in users]
                else:
                    urls = [url]

                for url in urls:
                    delay = 5
                    for _ in range(10):
                        try:
                            page = REQ.get(url, headers=headers)
                            data = json.loads(page)
                            assert data.get('status') != 'rate_limit_exceeded'
                            break
                        except Exception:
                            traceback.print_exc()
                            delay = min(100, delay * 2)
                            sys.stdout.write(f'url = {url}\n')
                            sys.stdout.write(f'Sleep {delay}... ')
                            sys.stdout.flush()
                            time.sleep(delay)
                            sys.stdout.write('Done\n')
                    else:
                        raise ExceptionParseStandings(f'Failed getting {n_page} by url {url}')

                    if 'status' in data and data['status'] != 'success':
                        LOG.warning(f'Skip url = {url}, data = {data}')
                        n_total_page = -1
                        continue

                    unscored_problems = data['contest_info']['unscored_problems']

                    if n_total_page is None:
                        for p in data['problems']:
                            if p['code'] in unscored_problems:
                                continue
                            d = problems_info
                            if 'division' in contest_info:
                                d = d.setdefault('division', OrderedDict())
                                d = d.setdefault(contest_info['division'], [])
                            code = p['code']

                            problem_info = {
                                'code': code,
                                'short': code,
                                'name': html.unescape(p['name']),
                                'url': self.PROBLEM_URL_FORMAT_.format(code=code),
                                'contest_key': key,
                            }
                            problem_infos[code] = problem_info
                            d.append(problem_info)

                            more_problem_info = self.get_problem_info(problem_info,
                                                                      contest=self.contest,
                                                                      cache=problems_data)
                            problem_info.update(more_problem_info)

                            for writer in problem_info.get('writers', []):
                                writers[writer] += 1

                        n_total_page = data['availablePages']
                        pbar = tqdm.tqdm(total=n_total_page * len(urls))
                        ranking_type = data['contest_info']['ranking_type']

                    for d in data['list']:
                        handle = d.pop('user_handle')
                        d.pop('html_handle', None)
                        problems_status = d.pop('problems_status')
                        if handle is None or d['score'] < 1e-9 and not problems_status:
                            LOG.warning(f'Skip handle = {handle}: {d}')
                            continue
                        row = result.setdefault(handle, OrderedDict())

                        row['member'] = handle
                        row['place'] = d.pop('rank')
                        row['solving'] = d.pop('score')
                        for k in 'time', 'total_time':
                            if k in d:
                                t = d.pop(k)
                                if t.startswith('-'):
                                    continue
                                row['time'] = t
                                break

                        stats = (statistics or {}).get(handle, {})
                        problems = row.setdefault('problems', stats.get('problems', {}))
                        clear_problems_fields(problems)
                        if problems_status:
                            solved, upsolved = 0, 0
                            for k, v in problems_status.items():
                                score = v.pop('score')
                                is_solved = False
                                is_scored = False

                                if ranking_type == '1' and 'penalty' in v and score == 1:
                                    penalty = v.pop('penalty')
                                    if score > 0:
                                        v['result'] = f'+{"" if penalty == 0 else penalty}'
                                    else:
                                        v['result'] = f'-{penalty}'
                                else:
                                    v['result'] = score
                                    is_scored = True
                                    penalty = 0

                                if score > 0:
                                    if k in unscored_problems:
                                        upsolved += 1
                                    else:
                                        solved += 1
                                        is_solved = True

                                if is_solved and is_scored and k in problem_infos and score:
                                    problem_infos[k]['max_score'] = max(problem_infos[k].get('max_score', 0), score)

                                if v.get('time'):
                                    time_in_seconds = 0
                                    for t in str(v['time']).split(':'):
                                        time_in_seconds = time_in_seconds * 60 + int(t)
                                    if penalty and attempt_penalty:
                                        time_in_seconds -= penalty * attempt_penalty
                                    v['time'] = self.to_time(time_in_seconds, num=3)
                                    v['time_in_seconds'] = time_in_seconds

                                problem = problems.setdefault(k, {})
                                if k in unscored_problems:
                                    problem_upsolving = problem.setdefault('upsolving', {})
                                    if not isinstance(problem_upsolving, dict):
                                        problem_upsolving = {'result': problem_upsolving}
                                        problem['upsolving'] = problem_upsolving
                                    problem = problem_upsolving
                                    if not is_improved_solution(v, problem):
                                        continue
                                problem.update(v)
                                to_update_partial.append((problem, k))
                            row['solved'] = {'solving': solved, 'upsolving': upsolved}

                        country = d.pop('country_code')
                        if country:
                            d['country'] = country

                        rating = as_number(d.pop('rating', None), force=True)
                        if rating:
                            row['old_rating'] = rating

                        row.update(d)
                        row.update(contest_info)
                        if statistics and handle in statistics:
                            stat = statistics[handle]
                            for k in ('old_rating', 'rating_change', 'new_rating'):
                                if k in stat:
                                    row[k] = stat[k]
                        hidden_fields |= set(list(d.keys()))
                    pbar.set_description(f'key={key} url={url}')
                    pbar.update()

            if not users:
                for problem, k in to_update_partial:
                    max_score = get_item(problem_infos, (k, 'max_score'))
                    if max_score and problem['result'] < max_score:
                        problem['partial'] = True
                    else:
                        problem.pop('partial', None)

            if pbar is not None:
                pbar.close()

        has_penalty = False
        for row in result.values():
            p = row.get('penalty')
            has_penalty = has_penalty or p and str(p) != "0"
        if not has_penalty:
            for row in result.values():
                row.pop('penalty', None)

        standings = {
            'result': result,
            'url': self.url,
            'problems': problems_info,
            'hidden_fields': list(hidden_fields),
            'options': options,
        }

        if is_frozen is not None:
            standings['has_hidden_results'] = is_frozen

        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers

        return standings

    @staticmethod
    def fetch_profle_page(user, /, req):
        for format_url in (
            Statistic.PROFILE_URL_FORMAT_,
            Statistic.TEAM_URL_FORMAT_,
        ):
            page = None
            page_url = None
            url = format_url.format(user=quote(user))
            response = Statistic._get(url, return_url=True, return_code=True, ignore_codes={404}, proxy=req)
            page, page_url, page_code = response
            if page_code == 404 or '/users/' not in page_url and '/teams/' not in page_url:
                page = None
            break
        return page, page_url

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        with REQ.with_proxy(
            time_limit=10,
            filepath_proxies='sharedfiles/resource/codechef/proxies',
            n_deferred=3,
            inplace=False,
        ) as req:
            fetch_profle_page_func = partial(Statistic.fetch_profle_page, req=req)
            for user, (page, url) in zip(users, map(fetch_profle_page_func, users)):
                if pbar:
                    pbar.update()

                if page is None:
                    yield {'delete': True}
                    continue

                match = re.search(r'jQuery.extend\(Drupal.settings,(?P<data>[^;]*)\);$', str(page), re.MULTILINE)
                data = json.loads(match.group('data'))
                if 'date_versus_rating' not in data:
                    info = {}
                    info['is_team'] = True
                    regex = '<table[^>]*cellpadding=""[^>]*>.*?</table>'
                    match = re.search(regex, page, re.DOTALL)
                    if match:
                        html_table = match.group(0)
                        table = parsed_table.ParsedTable(html_table)
                        for r in table:
                            for k, v in list(r.items()):
                                k = k.lower().replace(' ', '_')
                                info[k] = v.value

                    matches = re.finditer(r'''
                                          <td[^>]*>\s*<b[^>]*>Member[^<]*</b>\s*</td>\s*
                                          <td[^>]*><a[^>]*href\s*=\s*"[^"]*/users/(?P<member>[^"/]*)"[^>]*>
                                          ''', page, re.VERBOSE)
                    coders = set()
                    for match in matches:
                        coders.add(match.group('member'))
                    if coders:
                        info['members'] = list(coders)

                    ret = {'info': info, 'coders': coders}
                else:
                    data = data['date_versus_rating']['all']

                    matches = re.finditer(
                        r'''
                            <li[^>]*>\s*<label[^>]*>(?P<key>[^<]*):\s*</label>\s*
                            <span[^>]*>(?P<value>[^<]*)</span>\s*</li>
                        ''',
                        page,
                        re.VERBOSE,
                    )

                    info = {}
                    for match in matches:
                        key = match.group('key').strip().replace(' ', '_').lower()
                        value = match.group('value').strip()
                        info[key] = value

                    match = re.search('<h1[^>]*class="h2-style"[^>]*>(?P<name>[^<]*)</h1>', page)
                    if match:
                        info['name'] = html.unescape(match.group('name').strip())

                    match = re.search(r'''<header[^>]*>\s*<img[^>]*src=["'](?P<src>[^"']*)["'][^>]*>\s*<h1''', page)
                    if match:
                        src = urljoin(url, match.group('src'))
                        if 'default' not in src.split('/')[-1]:
                            response = requests.head(src)
                            if response.status_code < 400 and response.headers.get('Content-Length', '0') != '0':
                                info['avatar_url'] = src

                    contest_addition_update_params = {'clear_rating_change': True, 'try_fill_missed_ranks': True}
                    update = contest_addition_update_params.setdefault('update', {})
                    by = contest_addition_update_params.setdefault('by', ['key'])
                    prev_rating = None
                    for row in data:
                        rating = row.get('rating')
                        if not rating:
                            continue
                        rating = int(rating)
                        info['rating'] = rating

                        code = row.get('code')
                        name = row.get('name')
                        end_time = row.get('end_date')
                        if code:
                            if (
                                re.search(r'\bdiv[ision]*[-_\s]+[ABCD1234]\b', name, re.I)
                                and re.search('[ABCDE]$', code)
                                or re.search(r'^[A-Z]+[0-9]+[ABCD]$', code)
                            ):
                                code = code[:-1]

                            u = update.setdefault(code, OrderedDict())
                            u['new_rating'] = rating
                            if prev_rating is not None:
                                u['old_rating'] = prev_rating
                                u['rating_change'] = rating - prev_rating
                            u['_group'] = row['code']
                            u['_rank'] = row['rank']
                            u['_with_create'] = True

                            new_name = name
                            new_name = re.sub(r'\s*\([^\)]*\brated\b[^\)]*\)$', '', new_name, flags=re.I)
                            new_name = re.sub(r'\s*\bdiv(ision)?[-_\s]+[ABCD1234]$', '', new_name, flags=re.I)

                            if new_name != name:
                                if 'title' not in by:
                                    by.append('title')
                                update[new_name] = u

                            if row['code'] != u:
                                update[row['code']] = u

                            if end_time:
                                end_time = arrow.get(end_time)
                                year = str(end_time.year)
                                if code.endswith(year[-2:]) and not code.endswith(year):
                                    update[code[:-2] + year] = u

                        prev_rating = rating

                    ret = {
                        'info': info,
                        'contest_addition_update_params': contest_addition_update_params,
                    }

                yield ret

    @transaction.atomic()
    @staticmethod
    def update_submissions(account, resource):
        submissions_info = deepcopy(account.info.setdefault('submissions_', {}))
        submissions_info.setdefault('count', 0)
        if 'last_submission_time' not in submissions_info:
            submissions_info['count'] = 0
            submissions_info['last_id'] = -1
        last_id = submissions_info.setdefault('last_id', -1)
        last_submission_time = submissions_info.setdefault('last_submission_time', -1)
        new_last_id = last_id
        new_last_submission_time = last_submission_time

        ret = defaultdict(int)
        seen = set()
        contests_cache = dict()
        stats_cache = dict()

        @RateLimiter(max_calls=1, period=6)
        def fetch_submissions(page=0):
            url = Statistic.SUBMISSIONS_URL_.format(user=account.key, page=page)
            response = Statistic._get(url)
            data = json.loads(response)
            data['url'] = url
            data['page'] = page
            return data

        def get_contest(key, short):
            cache_key = key or short
            if cache_key in contests_cache:
                return contests_cache[cache_key]
            if key is None:
                problem = resource.problem_set.filter(key=short).first()
                if problem and problem.contest_id:
                    contest = problem.contest
                elif problem:
                    contest = None
                    for c in problem.contests.all():
                        exists = c.statistics_set.filter(account=account).exists()
                        if contest is None or exists:
                            contest = c
                            if exists:
                                break
                else:
                    contest = None
            else:
                f = Q(key=key)
                if re.search('[A-Z]$', key):
                    f |= Q(key=key[:-1])
                    entry = re.search('([0-9]+)$', key[:-1])
                    if entry and len(entry.group(1)) == 2:
                        f |= Q(key=key[:-3] + '20' + key[-3:-1])
                contest = resource.contest_set.filter(f).first()
            contests_cache[cache_key] = contest
            return contest

        def process_submission(data, current_url):
            nonlocal new_last_id, new_last_submission_time
            problem_info = {}
            submission_time = parse_datetime(data.pop('Time').value, timezone='+05:30')
            problem_info['submission_time'] = submission_time.timestamp()
            solution = data.pop('Solution')
            href = first(solution.column.node.xpath('.//a/@href'))
            if href is not None:
                url = urljoin(current_url, href)
                problem_info['url'] = url
                problem_info['id'] = int(url.rstrip('/').split('/')[-1])
            result = data.pop('Result')
            status = first(result.column.node.xpath('.//*/@title'))
            status = status.upper().split()
            status = status[0][:2] if len(status) == 1 else ''.join(s[0] for s in status)
            problem_info['verdict'] = status
            problem_info['language'] = data.pop('Lang').value
            score = result.value
            if score and (entry := re.match(r'^\((?P<score>[0-9]+)\)$', score)):
                problem_info['result'] = int(entry.group('score'))
                # FIXME: get full_score from contest problem info
                problem_info['partial'] = problem_info['result'] < 100
            else:
                problem_info['binary'] = True
                problem_info['result'] = int(problem_info['verdict'] == 'AC')

            if 'id' in problem_info:
                if last_id >= problem_info['id'] or problem_info['id'] in seen:
                    return False
                seen.add(problem_info['id'])
                new_last_id = max(new_last_id, problem_info['id'])

            if last_submission_time > (submission_time + timedelta(days=1)).timestamp():
                return False
            new_last_submission_time = max(new_last_submission_time, problem_info['submission_time'])

            name = data.pop('Problem')
            short = name.value
            href = first(name.column.node.xpath('.//a/@href'))
            contest_key = href.strip('/').split('/')[0]
            contest_key = None if contest_key == 'problems' else contest_key

            contest = get_contest(contest_key, short)
            if contest is None:
                LOG.warning(f'Missing contest for key = {contest_key} and short = {short}')
                ret.setdefault('missing_contests', set()).add((contest_key, short))
                return

            if contest in stats_cache:
                stat = stats_cache[contest]
            else:
                stat, _ = create_upsolving_statistic(contest=contest, account=account)
                stats_cache[contest] = stat

            problems = stat.addition.setdefault('problems', {})
            problem = problems.setdefault(short, {})
            if not is_improved_solution(problem_info, problem):
                return
            upsolving = problem.setdefault('upsolving', {})

            # previous version fix
            if not isinstance(upsolving, dict) or 'submission_time' not in upsolving:
                upsolving = {}

            if not is_improved_solution(problem_info, upsolving):
                return

            if not account.last_submission or account.last_submission < submission_time:
                account.last_submission = submission_time

            problem['upsolving'] = problem_info
            submissions_info['count'] += 1
            ret['n_updated'] += 1

            stat.save()

        def process_submissions(data):
            nonlocal max_page
            max_page = data['max_page']
            table = parsed_table.ParsedTable(data['content'])
            ret = False
            for r in table:
                result = process_submission(r, data['url'])
                if result is not False:
                    ret = True
            return ret

        def process_pagination():
            nonlocal max_page
            last_page = -1
            while max_page is None or last_page + 1 < max_page:
                last_page += 1
                data = fetch_submissions(last_page)
                if not process_submissions(data):
                    break

                with tqdm.tqdm(total=max_page - last_page - 1) as pbar:
                    for data in map(fetch_submissions, range(last_page + 1, max_page)):
                        result = process_submissions(data)
                        last_page = data['page']
                        pbar.update()
                        if not result:
                            return

        max_page = None
        process_pagination()

        submissions_info.update({
            'last_id': new_last_id,
            'last_submission_time': new_last_submission_time,
        })
        account.info['submissions_'] = submissions_info
        account.save(update_fields=['info', 'last_submission'])
        return ret

    @staticmethod
    @RateLimiter(max_calls=1, period=1)
    def get_problem_info(problem, contest, cache, **kwargs):
        code = problem['code']
        if code in cache:
            return cache[code]
        problem_info = cache.setdefault(code, {})

        problem_url = Statistic.API_PROBLEM_URL_FORMAT_.format(key='PRACTICE', code=code)
        problem_data = REQ.get(problem_url, return_json=True, ignore_codes={404, 403})

        if problem_data.get('status') == 'error':
            contest_key = problem.get('contest_key', contest.key)
            problem_info['url'] = Statistic.CONTEST_PROBLEM_URL_FORMAT_.format(key=contest_key, code=code)
            problem_url = Statistic.API_PROBLEM_URL_FORMAT_.format(key=contest_key, code=code)
            problem_data = REQ.get(problem_url, return_json=True, ignore_codes={404, 403})

        problem_data.pop('body', None)
        problem_data.pop('problemComponents', None)
        problem_data.pop('practice_special_banner', None)
        problem_data.pop('problem_display_authors_html_handle', None)

        problem_writers = []
        authors = problem_data.pop('problem_display_authors', None)
        if authors:
            problem_writers.extend(authors)
        author = problem_data.pop('problem_author', None)
        if author and author not in problem_writers:
            problem_writers.append(author)
        if problem_writers:
            problem_info['writers'] = problem_writers

        problem_tags = []
        for tags_field in ('tags', 'user_tags', 'computed_tags'):
            tags = problem_data.pop(tags_field, None)
            if not tags:
                continue
            if isinstance(tags, str):
                tags = re.findall('<a[^>]*>([^<]+)</a>', tags)
            problem_tags.extend(tags)
        if problem_tags:
            problem_info['tags'] = [slug(t) for t in problem_tags]
        languages_supported = problem_data.pop('languages_supported', None)
        if languages_supported:
            if isinstance(languages_supported, str):
                languages_supported = languages_supported.split(', ')
            problem_info['languages_supported'] = languages_supported

        native_rating = problem_data.pop('difficulty_rating', None)
        native_rating = as_number(native_rating, force=True)
        if native_rating and native_rating > 0:
            problem_info['native_rating'] = native_rating

        problem_info['is_challenge'] = problem_data.get('category_name') == 'challenge'

        for field in (
            ('hints'),
            ('best_tag'),
            ('editorial_url'),
            ('video_editorial_url'),
            ('max_timelimit'),
            ('source_sizelimit'),
            ('category_name'),
        ):
            if isinstance(field, tuple):
                key, field = field
            else:
                key = field
            value = problem_data.pop(key, None)
            if value:
                problem_info[field] = value

        return problem_info
