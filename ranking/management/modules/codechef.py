#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import json
import re
import sys
import time
import traceback
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import quote, urljoin

import arrow
import requests
import tqdm
from ratelimiter import RateLimiter

from ranking.management.modules import conf
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    STANDINGS_URL_FORMAT_ = 'https://www.codechef.com/rankings/{key}'
    API_CONTEST_URL_FORMAT_ = 'https://www.codechef.com/api/contests/{key}'
    API_RANKING_URL_FORMAT_ = 'https://www.codechef.com/api/rankings/{key}?sortBy=rank&order=asc&page={page}&itemsPerPage={per_page}'  # noqa
    API_PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/api/contests/{key}/problems/{code}'
    PROFILE_URL_FORMAT_ = 'https://www.codechef.com/users/{user}'
    PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/problems/{code}'
    CONTEST_PROBLEM_URL_FORMAT_ = 'https://www.codechef.com/{key}/problems/{code}'
    TEAM_URL_FORMAT_ = 'https://www.codechef.com/teams/view/{user}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self._username = conf.CODECHEF_USERNAME
        self._password = conf.CODECHEF_PASSWORD

    def get_standings(self, users=None, statistics=None):
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
            standings_url = self.STANDINGS_URL_FORMAT_.format(key=key)
            page = REQ.get(standings_url)
            for regex in (
                r'window.csrfToken\s*=\s*"([^"]*)"',
                '<input[^>]*name="csrfToken"[^>]*id="edit-csrfToken"[^>]*value="([^"]*)"',
            ):
                match = re.search(regex, page)
                if match:
                    break
            if not match:
                raise ExceptionParseStandings('not found csrf token')
            csrf_token = match.group(1)
            headers = {'x-csrf-token': csrf_token, 'x-requested-with': 'XMLHttpRequest'}

            n_page = 0
            per_page = 150
            n_total_page = None
            pbar = None
            ranking_type = None
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
                            delay = min(300, delay * 2)
                            sys.stdout.write(f'url = {url}\n')
                            sys.stdout.write(f'Sleep {delay}... ')
                            sys.stdout.flush()
                            time.sleep(delay)
                            sys.stdout.write('Done\n')
                    else:
                        raise ExceptionParseStandings(f'Failed getting {n_page} by url {url}')

                    if 'status' in data and data['status'] != 'success':
                        raise ExceptionParseStandings(json.dumps(data))

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
                            }
                            d.append(problem_info)

                            if code not in problems_data:
                                problem_url = self.API_PROBLEM_URL_FORMAT_.format(key='PRACTICE', code=code)
                                problem_data = REQ.get(problem_url,
                                                       headers=headers,
                                                       return_json=True,
                                                       ignore_codes={404})

                                if problem_data.get('status') == 'error':
                                    problem_info['url'] = self.CONTEST_PROBLEM_URL_FORMAT_.format(key=key, code=code)
                                    problem_url = self.API_PROBLEM_URL_FORMAT_.format(key=key, code=code)
                                    problem_data = REQ.get(problem_url, headers=headers, return_json=True)

                                writer = problem_data.get('problem_author')
                                if writer:
                                    writers[writer] += 1
                                    problems_data[code]['writers'] = [writer]

                                tags = problem_data.get('tags')
                                if tags:
                                    matches = re.findall('<a[^>]*>([^<]+)</a>', tags)
                                    problems_data[code]['tags'] = matches

                            problem_info.update(problems_data[code])

                        n_total_page = data['availablePages']
                        pbar = tqdm.tqdm(total=n_total_page * len(urls))
                        ranking_type = data['contest_info']['ranking_type']

                    for d in data['list']:
                        handle = d.pop('user_handle')
                        d.pop('html_handle', None)
                        problems_status = d.pop('problems_status')
                        if d['score'] < 1e-9 and not problems_status:
                            LOG.warning(f'Skip handle = {handle}: {d}')
                            continue
                        row = result.setdefault(handle, OrderedDict())

                        row['member'] = handle
                        row['place'] = d.pop('rank')
                        row['solving'] = d.pop('score')
                        for k in 'time', 'total_time':
                            if k in d:
                                row['time'] = d.pop(k)
                                break

                        problems = row.setdefault('problems', {})
                        solved, upsolved = 0, 0
                        if problems_status:
                            for k, v in problems_status.items():
                                t = 'upsolving' if k in unscored_problems else 'result'
                                v[t] = v.pop('score')
                                solved += 1 if v.get('result', 0) > 0 else 0
                                upsolved += 1 if v.get('upsolving', 0) > 0 else 0

                                if ranking_type == '1' and 'penalty' in v and v[t] == 1:
                                    penalty = v.pop('penalty')
                                    if v[t] > 0:
                                        v[t] = f'+{"" if penalty == 0 else penalty}'
                                    else:
                                        v[t] = f'-{penalty}'
                                else:
                                    penalty = 0

                                if v.get('time'):
                                    time_in_seconds = 0
                                    for t in str(v['time']).split(':'):
                                        time_in_seconds = time_in_seconds * 60 + int(t)
                                    if penalty and attempt_penalty:
                                        time_in_seconds -= penalty * attempt_penalty
                                    v['time'] = self.to_time(time_in_seconds, num=3)
                                    v['time_in_seconds'] = time_in_seconds

                                problems[k] = v
                            row['solved'] = {'solving': solved, 'upsolving': upsolved}
                        country = d.pop('country_code')
                        if country:
                            d['country'] = country

                        rating = d.pop('rating', None)
                        if rating and rating != '0':
                            hidden_fields.add('rating')
                            row['rating'] = rating

                        row.update(d)
                        row.update(contest_info)
                        if statistics and handle in statistics:
                            stat = statistics[handle]
                            for k in ('rating_change', 'new_rating'):
                                if k in stat:
                                    row[k] = stat[k]
                        hidden_fields |= set(list(d.keys()))
                    pbar.set_description(f'key={key} url={url}')
                    pbar.update()

            has_penalty = False
            for row in result.values():
                p = row.get('penalty')
                has_penalty = has_penalty or p and str(p) != "0"
            if not has_penalty:
                for row in result.values():
                    row.pop('penalty', None)

            if pbar is not None:
                pbar.close()

        standings = {
            'result': result,
            'url': self.url,
            'problems': problems_info,
            'hidden_fields': list(hidden_fields),
            'options': options,
        }

        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers

        return standings

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_profle_page(user):
            for format_url in (
                Statistic.PROFILE_URL_FORMAT_,
                Statistic.TEAM_URL_FORMAT_,
            ):
                page = None
                page_url = None
                url = format_url.format(user=quote(user))
                try:
                    ret = REQ.get(url, return_url=True)
                    if not ret:
                        continue
                    page, page_url = ret
                    if '/users/' not in page_url and '/teams/' not in page_url:
                        page = None
                    break
                except FailOnGetResponse as e:
                    if e.code == 404:
                        page = None
                    else:
                        raise e
            return page, page_url

        with PoolExecutor(max_workers=4) as executor:
            for user, (page, url) in zip(users, executor.map(fetch_profle_page, users)):
                if pbar:
                    pbar.update()

                if page is None:
                    yield {'info': None}
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

                    match = re.search(r'''<header[^>]*>\s*<img[^>]*src=["'](?P<src>[^"']*)["'][^>]*>\s*<h1''', page)
                    if match:
                        src = urljoin(url, match.group('src'))
                        if 'default' not in src.split('/')[-1]:
                            response = requests.head(src)
                            if response.status_code < 400 and response.headers.get('Content-Length', '0') != '0':
                                info['avatar_url'] = src

                    contest_addition_update_params = {}
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
                            if re.search(r'\bdiv(ision)?[-_\s]+[ABCD1234]\b', name, re.I) \
                               and re.search('[ABCD]$', code):
                                code = code[:-1]

                            u = update.setdefault(code, OrderedDict())
                            u['rating_change'] = rating - prev_rating if prev_rating is not None else None
                            u['new_rating'] = rating

                            new_name = name
                            new_name = re.sub(r'\s*\([^\)]*\brated\b[^\)]*\)$', '', new_name, flags=re.I)
                            new_name = re.sub(r'\s*\bdiv(ision)?[-_\s]+[ABCD1234]$', '', new_name, flags=re.I)

                            if new_name != name:
                                if 'title' not in by:
                                    by.append('title')
                                update[new_name] = u

                            if end_time:
                                end_time = arrow.get(end_time)
                                year = str(end_time.year)
                                if code.endswith(year[-2:]) and not code.endswith(year):
                                    update[code[:-2] + year] = u

                        prev_rating = rating

                    ret = {
                        'info': info,
                        'contest_addition_update_params': contest_addition_update_params,
                        'replace_info': True,
                    }

                yield ret
