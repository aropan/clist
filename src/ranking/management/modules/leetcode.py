#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import datetime, timedelta
from functools import lru_cache, partial
from pprint import pprint

import pytz
import tqdm
import yaml
from django.db import transaction
from ratelimiter import RateLimiter

from clist.templatetags.extras import is_solved
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, ProxyLimitReached

# from ranking.management.modules import conf


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://leetcode.com/contest/api/ranking/{key}/?pagination={{}}&region=global'
    RANKING_URL_FORMAT_ = '{url}/ranking'
    API_SUBMISSION_URL_FORMAT_ = 'https://leetcode{}.com/api/submissions/{}/'
    STATE_FILE = os.path.join(os.path.dirname(__file__), '.leetcode.yaml')

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @classmethod
    def _get(self, *args, req=None, **kwargs):
        req = req or REQ
        # if not getattr(self, '_authorized', None) and getattr(conf, 'LEETCODE_COOKIES', False):
        #     for kw in conf.LEETCODE_COOKIES:
        #         req.add_cookie(**kw)
        #     setattr(self, '_authorized', True)
        return req.get(*args, **kwargs)

    @staticmethod
    def fetch_submission(submission, req=REQ, raise_on_error=False):
        data_region = submission['data_region']
        data_region = '' if data_region == 'US' else f'-{data_region.lower()}'
        url = Statistic.API_SUBMISSION_URL_FORMAT_.format(data_region, submission['submission_id'])
        try:
            content = req.get(url)
            content = json.loads(content)
        except FailOnGetResponse as e:
            if raise_on_error:
                raise e
            content = {}
        except ProxyLimitReached:
            return submission, {'url': url}

        return submission, content

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url or self.RANKING_URL_FORMAT_.format(**self.__dict__)

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        url = api_ranking_url_format.format(1)
        content = Statistic._get(url)
        data = json.loads(content)
        if not data:
            return {'result': {}, 'url': standings_url}
        n_page = (data['user_num'] - 1) // len(data['total_rank']) + 1

        problems_info = OrderedDict((
            (
                str(p['question_id']),
                {
                    'code': p['question_id'],
                    'short': f'Q{i}',
                    'name': p['title'],
                    'url': os.path.join(self.url, 'problems', p['title_slug']),
                    'full_score': p['credit'],
                }
            )
            for i, p in enumerate(data['questions'], start=1)
        ))

        def update_problem_info(info):
            slug = info['url'].strip('/').rsplit('/', 1)[-1]
            params = {
                'operationName': 'questionData',
                'variables': {'titleSlug': slug},
                'query': 'query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { questionId difficulty contributors { profileUrl } topicTags { name } hints } }', # noqa
            }
            page = REQ.get(
                'https://leetcode.com/graphql',
                content_type='application/json',
                post=json.dumps(params).encode('utf-8'),
            )
            question = json.loads(page)['data']['question']
            if question:
                info['tags'] = [t['name'].lower() for t in question['topicTags']]
                info['writers'] = [
                    re.search('/(?P<username>[^/]*)/?$', c['profileUrl']).group('username').lower()
                    for c in question['contributors']
                ]
                if not info['writers']:
                    info['writers'] = ['leetcode']
                info['difficulty'] = question['difficulty'].lower()
                info['hints'] = question['hints']
            return info

        writers = defaultdict(int)
        with PoolExecutor(max_workers=8) as executor:
            for problem_info in executor.map(update_problem_info, problems_info.values()):
                for w in problem_info.get('writers', []):
                    writers[w] += 1

        @RateLimiter(max_calls=3, period=1)
        def fetch_page(page):
            url = api_ranking_url_format.format(page + 1)
            content = REQ.get(url)
            return json.loads(content)

        hidden_fields = set()
        result = {}
        stop = False
        rank_index0 = False
        if users is None or users:
            if users:
                users = list(users)
            start_time = self.start_time.replace(tzinfo=None)
            with PoolExecutor(max_workers=8) as executor:
                solutions_for_get = []

                for data in tqdm.tqdm(
                    executor.map(fetch_page, range(n_page)),
                    total=n_page,
                    desc='parsing statistics paging',
                ):
                    if stop:
                        break
                    n_added = 0
                    for row, submissions in zip(data['total_rank'], data['submissions']):
                        handle = row.pop('user_slug').lower()
                        if users is not None and handle not in users or handle in result:
                            continue
                        row.pop('contest_id')
                        row.pop('global_ranking')

                        r = result.setdefault(handle, OrderedDict())
                        r['member'] = handle
                        r['solving'] = row.pop('score')
                        r['name'] = row.pop('username')

                        rank = int(row.pop('rank'))
                        rank_index0 |= rank == 0
                        r['place'] = rank + (1 if rank_index0 else 0)

                        data_region = row.pop('data_region').lower()
                        r['info'] = {'profile_url': {'_data_region': '' if data_region == 'us' else f'-{data_region}'}}

                        country = None
                        for field in 'country_code', 'country_name':
                            country = country or row.pop(field, None)
                        if country:
                            r['country'] = country

                        problems_stats = (statistics or {}).get(handle, {}).get('problems', {})

                        solved = 0
                        problems = r.setdefault('problems', {})
                        for i, (k, s) in enumerate(submissions.items(), start=1):
                            short = problems_info[k]['short']
                            p = problems.setdefault(short, problems_stats.get(short, {}))
                            time = datetime.fromtimestamp(s['date']) - start_time
                            p['time_in_seconds'] = time.total_seconds()
                            p['time'] = self.to_time(time)
                            if s['status'] == 10:
                                solved += 1
                                p['result'] = '+' + str(s['fail_count'] or '')
                            else:
                                p['result'] = f'-{s["fail_count"]}'
                            if 'submission_id' in s:
                                p['submission_id'] = s['submission_id']
                                p['external_solution'] = True
                                p['data_region'] = s['data_region']
                                if 'language' not in p:
                                    s['handle'] = handle
                                    solutions_for_get.append(s)

                        if users:
                            users.remove(handle)
                            if not users:
                                stop = True

                        if not problems:
                            result.pop(handle)
                            continue

                        r['solved'] = {'solving': solved}
                        finish_time = datetime.fromtimestamp(row.pop('finish_time')) - start_time
                        r['penalty'] = self.to_time(finish_time)
                        r.update(row)
                        hidden_fields |= set(row.keys())
                        if statistics and handle in statistics:
                            stat = statistics[handle]
                            for k in ('rating_change', 'new_rating', 'raw_rating'):
                                if k in stat:
                                    r[k] = stat[k]
                        n_added += 1

                    if n_added == 0:
                        stop = True
            if statistics:
                for handle, row in statistics.items():
                    row['member'] = handle
                    result.setdefault(handle, row)

        standings = {
            'result': result,
            'url': standings_url,
            'hidden_fields': hidden_fields,
            'problems': list(problems_info.values()),
        }
        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers
        return standings

    @staticmethod
    def get_source_code(contest, problem):
        _, data = Statistic.fetch_submission(problem, raise_on_error=False)
        if not data:
            with REQ(
                with_proxy=True,
                args_proxy={
                    'time_limit': 3,
                    'n_limit': 30,
                    'filepath_proxies': os.path.join(os.path.dirname(__file__), '.leetcode.proxies'),
                    'connect': partial(Statistic.fetch_submission, problem, raise_on_error=True),
                },
            ) as req:
                _, data = req.proxer.get_connect_ret()

            if not data:
                return {}

        data['solution'] = data.pop('code', None)
        data['language'] = data.pop('lang', None)
        return data

    @staticmethod
    def is_china(account):
        profile_url = account.info.setdefault('profile_url', {})
        if profile_url.get('_data_region') is None:
            profile_url['_data_region'] = ''
            account.save()
        return '-cn' in profile_url['_data_region']

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        rate_limiter = RateLimiter(max_calls=1, period=4)

        @lru_cache()
        def get_all_contests(data_region=''):
            page = Statistic._get(
                f'https://leetcode{data_region}.com/graphql',
                post=b'{"variables":{},"query":"{allContests{titleSlug}}"}',
                content_type='application/json',
            )
            return json.loads(page)['data']

        def fetch_profile_data(req, account, raise_on_error=False, **kwargs):
            nonlocal stop
            nonlocal global_ranking_users
            nonlocal rate_limiter

            key = (account.info.get('profile_url', {}).get('_data_region'), account.key)
            if key in global_ranking_users:
                return account, global_ranking_users[key]

            if stop:
                return account, False

            connect_func = partial(fetch_profile_data, account=account, raise_on_error=True)
            req.proxer.set_connect_func(connect_func)

            page = False
            while True:
                try:
                    with rate_limiter:
                        if Statistic.is_china(account):
                            ret = {}

                            post = '''
                            {"operationName":"userPublicProfile","variables":{"userSlug":"''' + account.key + '''"},"query":"
                            query userPublicProfile($userSlug: String!) {
                                userProfilePublicProfile(userSlug: $userSlug) {
                                    username
                                    profile {
                                        userSlug
                                        realName
                                        contestCount
                                        ranking {
                                            currentLocalRanking
                                            currentGlobalRanking
                                            currentRating
                                            totalLocalUsers
                                            totalGlobalUsers
                                        }
                                    }
                                }

                                userContestRanking(userSlug: $userSlug) {
                                    ratingHistory
                                    contestHistory
                                }
                            }"}'''
                            post = re.sub(r'\s+', ' ', post)

                            page = Statistic._get(
                                'https://leetcode-cn.com/graphql',
                                post=post.encode(),
                                content_type='application/json',
                                req=req,
                                **kwargs,
                            )
                            ret['profile'] = json.loads(page)['data']
                            ranking = ret['profile'].pop('userContestRanking', None) or {}

                            ret['history'] = {
                                'titles': [h['title_slug'] for h in json.loads(ranking.get('contestHistory', '{}'))],
                                'ratings': json.loads(ranking.get('ratingHistory', '{}')),
                            }
                            page = ret
                        else:
                            page = Statistic._get(
                                'https://leetcode.com/graphql',
                                post=b'''
                                {"operationName":"getContentRankingData","variables":{"username":"''' + account.key.encode() + b'''"},"query":"query getContentRankingData($username: String!) {  userContestRanking(username: $username) {    attendedContestsCount    rating    globalRanking    __typename  }  userContestRankingHistory(username: $username) {    contest {      title      startTime      __typename    }    rating    ranking    __typename  }}"}''',  # noqa
                                content_type='application/json',
                            )
                            page = json.loads(page)['data']
                            page['slug'] = account.key
                    break
                except FailOnGetResponse as e:
                    code = e.code
                    if code == 404:
                        page = None
                        break

                    if Statistic.is_china(account):
                        if raise_on_error:
                            raise e

                        ret = req.proxer.get_connect_ret()
                        if ret:
                            return ret
                    else:
                        page = False
                        if code in [403, 429]:
                            stop = True
                        break
                except ProxyLimitReached:
                    return account, {}

            return account, page

        @RateLimiter(max_calls=2, period=1)
        def fetch_global_ranking_users(req, page_index, raise_on_error=False, **kwargs):
            connect_func = partial(fetch_global_ranking_users, page_index=page_index, raise_on_error=True)
            req.proxer.set_connect_func(connect_func)

            while True:
                try:
                    post = '''{
                        "operationName":"null",
                        "variables":{},
                        "query":"{
                            globalRanking(page: ''' + str(page_index) + ''') {
                                rankingNodes {
                                    dataRegion
                                    user {
                                        username
                                        profile {
                                            userSlug
                                            realName
                                            contestCount
                                            ranking {
                                                ranking
                                                currentLocalRanking
                                                currentGlobalRanking
                                                currentRating
                                                ratingProgress
                                                totalLocalUsers
                                                totalGlobalUsers
                                            }
                                        }
                                    }
                                }
                            }
                        }"
                    }'''
                    post = re.sub(r'\s+', ' ', post)

                    page = Statistic._get(
                        'https://leetcode-cn.com/graphql',
                        post=post.encode(),
                        content_type='application/json',
                        req=req,
                        **kwargs,
                    )
                    data = json.loads(page)['data']
                    break
                except FailOnGetResponse as e:
                    if raise_on_error:
                        raise e

                    ret = req.proxer.get_connect_ret()
                    if ret:
                        return ret
                except ProxyLimitReached:
                    return page_index, None

            return page_index, data

        with REQ(
            with_proxy=True,
            args_proxy={'time_limit': 10, 'n_limit': 30},
        ) as req:
            if os.path.exists(Statistic.STATE_FILE):
                with open(Statistic.STATE_FILE, 'r') as fo:
                    state = yaml.safe_load(fo)
            else:
                state = {}

            last_page = state.setdefault('last_page', 0)

            # n_accounts_to_paging = state.setdefault('n_accounts_to_paging', 1000)
            # pages_per_update = state.setdefault('pages_per_update', 200)
            # if len(accounts) > n_accounts_to_paging:
            #     if (
            #         'next_time' in state
            #         and datetime.now() < state['next_time']
            #         and last_page == 0
            #     ):
            #         for a in accounts:
            #             a.updated += timedelta(days=365)
            #             a.save()
            #         next_page = last_page
            #     else:
            #         next_page = last_page + pages_per_update
            #     pages = set(list(range(last_page + 1, next_page + 1)))
            #     stop = True
            # else:
            #     pages = set()
            #     stop = False

            pages, stop = set(), False

            # for a in tqdm.tqdm(accounts, desc='getting global ranking pages'):
            #     if len(pages) > pages_per_update * 2:
            #         break
            #     if 'global_ranking_page' in a.info:
            #         page = a.info['global_ranking_page']
            #         pages.add(page)
            #         if stop:
            #             a.info.pop('global_ranking_page')
            #             a.save()

            global_ranking_users = {}
            n_data = 0
            fetch_global_ranking_users_func = partial(fetch_global_ranking_users, req)
            with tqdm.tqdm(desc='global rank paging', total=len(pages)) as pb:
                for page, data in map(fetch_global_ranking_users_func, sorted(pages)):
                    pb.set_postfix(page=page, last_page=last_page, n_data=n_data)
                    pb.update()
                    if data is None:
                        break
                    n_data += 1
                    if data:
                        data = data['globalRanking']['rankingNodes']
                    if data:
                        if page == last_page + 1:
                            last_page = page
                            state['last_page'] = last_page
                        for node in data:
                            data_region = node['dataRegion'].lower()
                            data_region = '' if data_region == 'us' else f'-{data_region}'
                            username = node['user']['profile']['userSlug'].lower()
                            global_ranking_users[(data_region, username)] = {
                                'profile': {'userProfilePublicProfile': node['user']},
                            }
                    else:
                        state['last_page'] = 0
                        state['next_time'] = datetime.now() + timedelta(hours=8)

                        if stop:
                            for a in accounts:
                                a.updated = state['next_time']
                                a.save()
                        break

            if stop:
                with open(Statistic.STATE_FILE, 'w') as fo:
                    yaml.dump(state, fo, indent=2)

            fetch_profile_data_func = partial(fetch_profile_data, req)
            for account, page in map(fetch_profile_data_func, accounts):
                if pbar:
                    pbar.set_postfix(stop=stop)
                    pbar.update()

                if not page:
                    if page is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue

                info = {}
                contest_addition_update_by = None
                ratings, rankings, titles = [], [], []
                if Statistic.is_china(account) or isinstance(page, dict) and 'contests' in page:
                    info = page.pop('profile')['userProfilePublicProfile']
                    if info is None:
                        yield {'info': None}
                        continue
                    contest_addition_update_by = 'key'
                    info.update(info.pop('profile', {}) or {})
                    info.update(info.pop('ranking', {}) or {})
                    info.update(page.pop('history', {}) or {})
                    info['slug'] = info.pop('userSlug')

                    if 'titles' in info:
                        titles = info.pop('titles')
                    else:
                        contests = [c['titleSlug'] for c in page['contests']['allContests']]
                        titles = list(reversed(contests))

                    if 'rankings' in info:
                        rankings = info.pop('rankings')
                    elif 'ranking' in info:
                        rankings = yaml.safe_load(info.pop('ranking'))

                    if 'ratings' in info:
                        ratings = info.pop('ratings')
                    else:
                        ratings = info.pop('ratingProgress', []) or []

                    if 'currentRating' in info:
                        info['rating'] = int(info['currentRating'])
                else:
                    if page['userContestRankingHistory'] is None:
                        yield {'info': None}
                        continue
                    contest_addition_update_by = 'title'
                    for history in page['userContestRankingHistory']:
                        ratings.append(history['rating'])
                        rankings.append(history['ranking'])
                        titles.append(history['contest']['title'])
                    global_ranking = (page.get('userContestRanking') or {}).get('globalRanking')
                    if global_ranking is not None:
                        info['global_ranking'] = global_ranking
                    info['slug'] = page['slug']

                for k in ('profile_url', ):
                    if k in account.info:
                        info[k] = account.info[k]

                if not rankings:
                    rankings = [-1] * len(ratings)

                contest_addition_update = {}
                prev_rating = None
                last_rating = None
                if ratings and titles:
                    for rating, ranking, title in zip(ratings, rankings, titles):
                        if ranking > 0 or prev_rating != rating and (prev_rating is not None or rating != 1500):
                            int_rating = round(rating)
                            update = contest_addition_update.setdefault(title, OrderedDict())
                            update['rating_change'] = int_rating - last_rating if last_rating is not None else None
                            update['new_rating'] = int_rating
                            update['raw_rating'] = rating
                            last_rating = int_rating
                        prev_rating = rating
                if last_rating and 'rating' not in info:
                    info['rating'] = last_rating

                if 'global_ranking' in info:
                    global_ranking = int(re.split('[^0-9]', str(info['global_ranking']))[0])
                elif 'currentGlobalRanking' in info:
                    global_ranking = info['currentGlobalRanking']
                else:
                    global_ranking = None
                if global_ranking:
                    page = (int(global_ranking) + 24) // 25
                    info['global_ranking_page'] = page

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': contest_addition_update_by,
                        'clear_rating_change': True,
                    },
                    'replace_info': True,
                }

                assert info and info['slug'].lower() == account.key, \
                    f'Account key {account.key} should be equal username {info["slug"]}'

                yield ret

    @transaction.atomic()
    @staticmethod
    def update_submissions(account, resource):

        def recent_accepted_submissions(req=REQ):

            if Statistic.is_china(account):
                post = '''
                {"query":"query recentAcSubmissions($userSlug: String!) { recentACSubmissions(userSlug: $userSlug) { submissionId submitTime question { title translatedTitle titleSlug questionFrontendId } } } ","variables":{"userSlug":"''' + account.key + '''"},"operationName":"recentAcSubmissions"}
                '''
                page = Statistic._get(
                    'https://leetcode.cn/graphql/noj-go/',
                    content_type='application/json',
                    post=post.encode(),
                    req=req,
                )
                data = json.loads(page)['data']['recentACSubmissions']
            else:
                post = '''
                {"query":"query recentAcSubmissions($username: String!, $limit: Int!) { recentAcSubmissionList(username: $username, limit: $limit) { id title titleSlug timestamp } } ","variables":{"username":"''' + account.key + '''","limit":20},"operationName":"recentAcSubmissions"}
                '''
                page = Statistic._get(
                    'https://leetcode.com/graphql',
                    content_type='application/json',
                    post=post.encode(),
                    req=req,
                )
                data = json.loads(page)['data']['recentAcSubmissionList']
            return data

        ret = defaultdict(int)
        submissions = recent_accepted_submissions()
        save_account = False
        for submission in submissions:

            def get_field(*fields):
                for field in fields:
                    if field in submission:
                        return submission.pop(field)
                raise KeyError(f'No field {fields} in {submission}')

            submission_time = int(get_field('timestamp', 'submitTime'))
            submission_id = get_field('id', 'submissionId')
            if 'question' in submission:
                submission.update(submission.pop('question'))
            title_slug = get_field('titleSlug')

            regex = '/' + re.escape(title_slug) + '/?$'
            qs = resource.problem_set.filter(url__regex=regex)
            problems = qs[:2]
            if len(problems) != 1:
                LOG.warning(f'Wrong problems = {problems} for title slug = {title_slug}')
                ret['n_missing_problem'] += 1
                continue
            problem = problems[0]
            contests = set(problem.contests.all()[:2])
            if problem.contest:
                contests.add(problem.contest)
            if len(contests) != 1:
                LOG.warning(f'Wrong contests = {contests} for problem = {problem}')
                ret['n_missing_contest'] += 1
                continue
            contest = next(iter(contests))
            short = problem.short

            if problem.name != get_field('title'):
                LOG.warning(f'Problem {problem} has wrong name {problem.name}')
                ret['n_wrong_problem_name'] += 1
                continue

            stat, created = contest.statistics_set.get_or_create(account=account)
            if created:
                stat.addition.setdefault('_no_update_n_contests', True)
            problems = stat.addition.setdefault('problems', {})
            problem = problems.setdefault(short, {})
            upsolving = problem.setdefault('upsolving', {})
            if is_solved(problem) or is_solved(upsolving):
                ret['n_already_solved'] += 1
                continue
            upsolving = dict(
                binary=True,
                result='+',
                submission_id=submission_id,
                submission_time=submission_time,
            )
            problem['upsolving'] = upsolving
            ret['n_updated'] += 1
            stat.save()

            submission_time = datetime.fromtimestamp(submission_time).replace(tzinfo=pytz.utc)
            if not account.last_submission or account.last_submission < submission_time:
                account.last_submission = submission_time
                save_account = True

        if save_account:
            account.save()
        return ret


if __name__ == "__main__":
    statictic = Statistic(
        name='Biweekly Contest 18',
        url='https://leetcode.com/contest/biweekly-contest-18/',
        key='biweekly-contest-18',
        start_time=datetime.now(),
        standings_url=None,
    )
    pprint(next(iter(statictic.get_standings()['result'].values())))
