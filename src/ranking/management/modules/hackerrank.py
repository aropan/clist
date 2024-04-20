# -*- coding: utf-8 -*-

import collections
import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack
from time import sleep
from urllib.parse import urljoin

from ratelimiter import RateLimiter
from tqdm import tqdm

from clist.templatetags.extras import as_number, get_problem_key
from ranking.management.modules.common import LOG, REQ, UNCHANGED, BaseModule, FailOnGetResponse, utc_now
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    DELAY = 1
    MAX_WORKERS = 8

    @staticmethod
    def get(url):
        n_attempts = 0
        while True:
            try:
                Statistic.DELAY *= 0.9
                Statistic.DELAY = max(0.5, min(Statistic.DELAY, 10))
                sleep(Statistic.DELAY)
                page = REQ.get(url)
                break
            except FailOnGetResponse as e:
                n_attempts += 1
                if e.code == 429 and n_attempts < 10:
                    Statistic.DELAY *= 1.5
                    continue
                raise e
        return page

    def get_standings(self, users=None, statistics=None):

        standings_url = self.url.rstrip('/') + '/leaderboard'

        per_page = 100
        if '/contests/' in self.url:
            api_standings_url_format = standings_url.replace('/contests/', '/rest/contests/')
            api_standings_url_format += '?offset={offset}&limit={limit}'
            fetching_problems = True
        elif '/competitions/' in self.url:
            url = self.host + f'api/hrw/resources/{self.key}?include=leaderboard'
            page = REQ.get(url)
            data = json.loads(page)
            entry_id = data['included'][0]['id']
            api_standings_url_format = self.host + f'api/hrw/resources/leaderboards/{entry_id}/leaderboard_entries'
            api_standings_url_format += '?page[limit]={limit}&page[offset]={offset}'
            fetching_problems = False
        else:
            raise ExceptionParseStandings(f'Unusual url = {self.url}')

        @RateLimiter(max_calls=1, period=2)
        def fetch_page(page):
            offset = (page - 1) * per_page
            url = api_standings_url_format.format(offset=offset, limit=per_page)
            page = Statistic.get(url)
            data = json.loads(page)
            data['total'] = data['meta']['record_count'] if 'meta' in data else data['total']
            data['pages'] = (data['total'] - 1) // (per_page) + 1
            return data

        result = {}
        hidden_fields = set()
        schools = dict()

        def process_data(data):
            rows = data['models'] if 'models' in data else data['data']

            school_ids = set()
            for r in rows:
                if isinstance(r.get('attributes'), dict):
                    r = r['attributes']

                def get(*fields):
                    for f in fields:
                        if f in r:
                            return r.pop(f)

                handle = get('hacker', 'name')
                if handle is None:
                    continue
                row = result.setdefault(handle, collections.OrderedDict())
                row['member'] = handle
                score = get('score', 'solved_challenges')
                if score is None:
                    score = get('percentage_score') * 100
                row['solving'] = score
                row['place'] = get('rank', 'leaderboard_rank')
                time = get('time_taken', 'time_taken_seconds')
                if time:
                    row['time'] = self.to_time(time, 3)

                country = get('country')
                if country:
                    row['country'] = country

                avatar_url = get('avatar')
                if avatar_url:
                    row['info'] = {'avatar_url': avatar_url}

                if statistics and handle in statistics:
                    stat = statistics[handle]
                    for k in ('old_rating', 'rating_change', 'new_rating', 'problems'):
                        if k in stat:
                            row[k] = stat[k]

                challenges = r.pop('challenges', None) or []
                for challenge in challenges:
                    attempts = challenge['submissions']
                    if not attempts:
                        continue

                    time_taken = challenge['time_taken']
                    problems = row.setdefault('problems', {})
                    problem_key = get_problem_key(problems_infos[challenge['slug']])
                    problem = problems.setdefault(problem_key, {})
                    if time_taken:
                        problem['time'] = self.to_time(time_taken, 3)
                        problem['time_in_seconds'] = time
                        problem['result'] = f'+{attempts - 1}' if attempts > 1 else '+'
                    else:
                        problem['result'] = f'-{attempts}'
                    penalty = challenge['penalty']
                    if penalty:
                        problem['penalty_time'] = penalty

                for k, v in r.items():
                    if k not in row and v is not None:
                        row[k] = v
                        hidden_fields.add(k)

                if 'school_id' in row and row['school_id'] not in schools:
                    school_ids.add(row['school_id'])

            if school_ids:
                query = ','.join(school_ids)
                url = self.host + f'community/v1/schools?page[limit]={len(school_ids)}&filter[unique_id]={query}'
                page = REQ.get(url)
                data = json.loads(page)
                for s in data['data']:
                    schools[s['id']] = s['attributes']['name']

            for row in result.values():
                if 'school_id' in row and 'school' not in row and row['school_id'] in schools:
                    row['school'] = schools[row['school_id']]

        def fetch_problems():
            problems_url = self.url.rstrip('/') + '/challenges'
            api_problems_url = problems_url.replace('/contests/', '/rest/contests/')
            offset = 0
            limit = 50
            ret = collections.OrderedDict()
            seen = set()
            data = None
            while True:
                url = f'{api_problems_url}?offset={offset}&limit={limit}'
                try:
                    page = Statistic.get(url)
                except FailOnGetResponse as e:
                    if e.code == 404:
                        break
                    raise e
                data = json.loads(page)
                added = 0
                for problem_model in data['models']:
                    code = problem_model.pop('id')
                    if code not in seen:
                        added += 1
                        seen.add(code)
                    slug = problem_model.pop('slug')
                    problem_info = {
                        'code': code,
                        'name': problem_model.pop('name'),
                        'slug': slug,
                        'url': f'{problems_url}/{slug}/problem'
                    }
                    full_score = problem_model.pop('max_score', None)
                    if full_score:
                        problem_info['full_score'] = full_score
                    for tag in problem_model.pop('tag_names'):
                        problem_info.setdefault('tags', []).append(tag.lower())
                    problem_info['_more_fields'] = problem_model
                    ret[code] = problem_info
                if added < limit:
                    break
                offset += limit
            if data is not None and data['total'] != len(seen):
                raise ExceptionParseStandings(f'Not all problems are fetched: {len(seen)} of {data["total"]}')

            return ret

        problem_info = None

        def process_problem_data(data):
            rows = data['models'] if 'models' in data else data['data']
            for r in rows:
                handle = r.pop('hacker')
                if handle not in result:
                    if statistics and handle in statistics:
                        row = copy.deepcopy(statistics[handle])
                        row['place'] = UNCHANGED
                        row['solving'] = UNCHANGED
                    else:
                        row = {}
                    row['member'] = handle
                    result[handle] = row
                score = as_number(r['score'])
                problem = {'result': score}
                if 'full_score' in problem_info:
                    problem['partial'] = score < problem_info['full_score']
                time = r.get('time_taken')
                if time:
                    problem['time'] = self.to_time(time, 3)
                    problem['time_in_seconds'] = time
                language = r.get('language')
                if language:
                    problem['language'] = language

                problem_key = get_problem_key(problem_info)
                problems = result[handle].setdefault('problems', {})
                problems[problem_key] = problem

        try:
            data = fetch_page(1)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e

        problems_infos = collections.OrderedDict()
        with_submissions = False

        if data.get('contest_challenges'):
            for challenge in data['contest_challenges']:
                slug = challenge['slug']
                problems_infos[slug] = {
                    'short': challenge['letter'],
                    'name': challenge['name'],
                    'slug': slug,
                    'url': f'{self.url}/challenges/{slug}/problem',
                }

        if fetching_problems and not problems_infos:
            problems_infos = fetch_problems()
            with_submissions = True

        process_data(data)

        pages_limit = self.resource.info['statistics']['pages_limit']
        pages_offset = self.info.pop('_pages_offset', 1)
        total_pages = data['pages']
        pages_limited = total_pages > pages_limit
        if pages_limited:
            LOG.warning(f'Limit number of pages from {total_pages} to {pages_limit}, offset = {pages_offset}')
        is_over = self.end_time < utc_now()
        with_submissions = with_submissions and (is_over or not pages_limited) and len(problems_infos)
        if with_submissions:
            pages_limit = max(1, round(pages_limit / (len(problems_infos) / 4 + 1)))
            LOG.warning(f'Limit number of pages with submissions = {pages_limit}')
        pages_limited = pages_limit < total_pages
        n_pages = min(pages_limit, total_pages)

        with ExitStack() as stack:
            executor = stack.enter_context(PoolExecutor(max_workers=Statistic.MAX_WORKERS))

            pages = list(range(max(2, pages_offset), min(pages_offset + n_pages, data['pages'] + 1)))
            pbar = stack.enter_context(tqdm(total=len(pages), desc='getting pages'))
            for data in executor.map(fetch_page, pages):
                process_data(data)
                pbar.set_postfix(delay=f'{Statistic.DELAY:.5f}', refresh=False)
                pbar.update()

            if with_submissions:
                for problem_info_ in problems_infos.values():
                    problem_info = problem_info_
                    standings_problem_url = re.sub('/problem$', '/leaderboard', problem_info['url'])
                    api_standings_url_format = standings_problem_url.replace('/contests/', '/rest/contests/')
                    api_standings_url_format += '?offset={offset}&limit={limit}'

                    data = fetch_page(1)
                    process_problem_data(data)

                    problem_pages = min(n_pages, data['pages'])
                    pages = list(range(max(2, pages_offset), min(pages_offset + problem_pages, data['pages'] + 1)))
                    pbar = stack.enter_context(tqdm(total=len(pages), desc=f'getting pages {problem_info["slug"]}'))
                    for data in executor.map(fetch_page, pages):
                        process_problem_data(data)
                        pbar.set_postfix(delay=f'{Statistic.DELAY:.5f}', refresh=False)
                        pbar.update()

        n_empty_problems = 0
        for row in result.values():
            n_empty_problems += bool(row.get('solving') and not row.get('problems'))
        skip_problem_rating = problems_infos and n_empty_problems >= len(result) * 0.1

        standings = {
            'result': result,
            'hidden_fields': list(hidden_fields),
            'problems': list(problems_infos.values()),
            'skip_problem_rating': skip_problem_rating,
            'url': standings_url,
            'keep_results': pages_limited,
        }

        pages_offset += n_pages
        if pages_offset <= total_pages:
            standings['_pages_offset'] = pages_offset
            standings['_reparse_statistics'] = True
            standings['skip_problem_rating'] = True
            standings.setdefault('info_fields', []).extend(['_pages_offset', '_reparse_statistics'])

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=Statistic.MAX_WORKERS, period=1)
        def fetch_profile(user):
            url = urljoin(resource.url, f'/rest/contests/master/hackers/{user}/profile')
            try:
                page = Statistic.get(url)
            except FailOnGetResponse as e:
                code = e.code
                if code == 404:
                    return None
                return {}
            page = page.replace(r'\u0000', '')
            data = json.loads(page)
            if not data:
                return None
            data = data['model']

            url = urljoin(resource.url, f'/rest/hackers/{user}/rating_histories_elo')
            page = Statistic.get(url)
            data['ratings'] = json.loads(page)['models']
            return data

        with PoolExecutor(max_workers=Statistic.MAX_WORKERS) as executor:
            profiles = executor.map(fetch_profile, users)
            for user, data in zip(users, profiles):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                data = {k: v for k, v in data.items() if v is not None and (v or not isinstance(v, str))}

                info = {}

                country = data.pop('country', None)
                if country:
                    info['country'] = country

                school = data.pop('school', None)
                if school:
                    info['school'] = school

                avatar_url = data.pop('avatar', None)
                if avatar_url:
                    info['avatar_url'] = avatar_url

                info['name'] = data.pop('name', None)

                contest_addition_update = {}

                ratings = data.pop('ratings', None)
                if ratings:
                    for category in ratings:
                        last_rating = None
                        for rating in category['events']:
                            update = collections.OrderedDict()
                            new_rating = int(rating['rating'])
                            if last_rating is not None:
                                update['old_rating'] = last_rating
                                update['rating_change'] = new_rating - last_rating
                            update['new_rating'] = new_rating
                            last_rating = new_rating

                            for field in ('contest_slug', 'contest_name'):
                                if rating.get(field):
                                    update['_group'] = rating[field]
                                    break

                            contest_name = rating['contest_name']
                            for contest_key in {contest_name, contest_name.strip()}:
                                contest_addition_update[contest_key] = update

                        if last_rating is not None and category['category'].lower() == 'algorithms':
                            info['rating'] = last_rating

                info['data_'] = data

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': 'title',
                        'clear_rating_change': True,
                    },
                }

                if user.lower() != data['username'].lower():
                    ret['rename'] = data['username']

                yield ret
