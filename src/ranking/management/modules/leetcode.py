#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import hashlib
import json
import os
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache, partial
from urllib.parse import urljoin

import pytz
import tqdm
import yaml
from django.db import transaction
from django.utils.timezone import now
from ratelimiter import RateLimiter

from clist.templatetags.extras import get_item, is_improved_solution
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, ProxyLimitReached
from ranking.utils import clear_problems_fields, create_upsolving_statistic
from utils.logger import suppress_db_logging_context
from utils.timetools import datetime_from_timestamp

# from ranking.management.modules import conf


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://leetcode.com/contest/api/ranking/{key}/?pagination={{}}&region=global'
    QUESTIONS_URL_FORMAT_ = 'https://leetcode.com/contest/api/info/{key}/'
    RANKING_URL_FORMAT_ = '{url}/ranking'
    API_SUBMISSION_URL_FORMAT_ = 'https://leetcode{}/api/submissions/{}/'
    STATE_FILE = os.path.join(os.path.dirname(__file__), '.leetcode.yaml')
    DOMAINS = {'': '.com', 'us': '.com', 'cn': '.cn'}
    API_SUBMISSIONS_URL_FORMAT_ = 'https://leetcode.com/api/submissions/?offset={}&limit={}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @classmethod
    def _get(self, *args, req=None, n_addition_attempts=20, **kwargs):
        req = req or REQ

        headers = kwargs.setdefault('headers', {})
        headers['User-Agent'] = 'Mediapartners-Google'
        headers['Accept-Encoding'] = 'gzip, deflate, br'

        for key, value in (
            ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'),
            ('Accept-Language', 'en-US,en;q=0.5'),
            ('Connection', 'keep-alive'),
            ('DNT', '1'),
            ('Upgrade-Insecure-Requests', '1'),
            ('Sec-Fetch-Dest', 'document'),
            ('Sec-Fetch-Mode', 'navigate'),
            ('Sec-Fetch-Site', 'cross-site'),
            ('Pragma', 'no-cache'),
            ('Cache-Control', 'no-cache'),
        ):
            headers.setdefault(key, value)

        kwargs['with_curl'] = req.proxer is None and 'post' not in kwargs
        kwargs['with_referer'] = False

        # if not getattr(self, '_authorized', None) and getattr(conf, 'LEETCODE_COOKIES', False):
        #     for kw in conf.LEETCODE_COOKIES:
        #         req.add_cookie(**kw)
        #     setattr(self, '_authorized', True)

        additional_attempts = {code: {'count': n_addition_attempts} for code in [429, 403]}
        return req.get(*args, **kwargs, additional_attempts=additional_attempts, additional_delay=5)

    @staticmethod
    def _get_proxies_file(region):
        return os.path.join(os.path.dirname(__file__), f'.leetcode.{region or "DEFAULT"}.proxies')

    @staticmethod
    def fetch_submission(submission, req=REQ, raise_on_error=False, n_attempts=1):
        data_region = submission['data_region']
        domain = Statistic.DOMAINS[data_region.lower()]
        url = Statistic.API_SUBMISSION_URL_FORMAT_.format(domain, submission['submission_id'])
        try:
            content = Statistic._get(url, req=req, n_attempts=n_attempts, n_addition_attempts=0)
            content = json.loads(content)
        except FailOnGetResponse as e:
            if raise_on_error:
                raise e
            content = {}

        return submission, content

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url or self.RANKING_URL_FORMAT_.format(**self.__dict__)

        api_ranking_url_format = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        url = api_ranking_url_format.format(1)
        content = Statistic._get(url)
        data = json.loads(content)
        if not data:
            return {'result': {}, 'url': standings_url}

        questions_url = self.QUESTIONS_URL_FORMAT_.format(**self.__dict__)
        page = Statistic._get(questions_url)
        questions_data = json.loads(page)

        problems_info = OrderedDict((
            (
                str(p['question_id']),
                {
                    'code': p['question_id'],
                    'short': f'Q{i}',
                    'name': p['title'],
                    'url': os.path.join(self.url, 'problems', p['title_slug']),
                    'full_score': p['credit'],
                    'slug': p['title_slug'],
                }
            )
            for i, p in enumerate(questions_data['questions'], start=1)
        ))

        def update_problem_info(info):
            slug = info['url'].strip('/').rsplit('/', 1)[-1]
            params = {
                'operationName': 'questionData',
                'variables': {'titleSlug': slug},
                'query': 'query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { questionId difficulty contributors { profileUrl } topicTags { name } hints } }',  # noqa: E501
            }
            page = Statistic._get(
                'https://leetcode.com/graphql',
                content_type='application/json',
                post=json.dumps(params).encode('utf-8'),
                n_attempts=3,
            )
            question = json.loads(page)['data']['question']
            if question:
                info['tags'] = [t['name'].lower() for t in question['topicTags']]
                info['difficulty'] = question['difficulty'].lower()
                info['hints'] = question['hints']
            return info

        with PoolExecutor(max_workers=8) as executor:
            executor.map(update_problem_info, problems_info.values())

        fetch_page_rate_limiter = RateLimiter(max_calls=4, period=1)

        def fetch_page(page):
            if stop:
                return
            with fetch_page_rate_limiter:
                url = api_ranking_url_format.format(page + 1)
                content = Statistic._get(url, ignore_codes={404}, n_attempts=3)
                data = json.loads(content)
                return data

        n_top_submissions = get_item(self.resource.info, 'statistics.n_top_download_submissions')

        hidden_fields = set()
        parsed_domains = set()
        badges = set()
        result = {}
        stop = False
        if users is None or users:
            if users:
                users = list(users)
            start_time = self.start_time.replace(tzinfo=None)
            with PoolExecutor(max_workers=4) as executor:
                solutions_for_get = []
                solutions_ids = set()
                times = {}

                def fetch_ranking(domain, region):
                    nonlocal api_ranking_url_format, stop, hidden_fields, parsed_domains
                    api_ranking_url_format = re.sub('[.][^./]+(?=/)', domain, api_ranking_url_format)
                    api_ranking_url_format = re.sub('&region=[^&]+', f'&region={region}', api_ranking_url_format)

                    stop = False

                    try:
                        data = fetch_page(1)
                    except FailOnGetResponse as e:
                        if e.code == 404:
                            return
                        raise e
                    if not data:
                        return
                    for p in data['questions']:
                        if str(p['question_id']) not in problems_info:
                            return

                    n_page = (data['user_num'] - 1) // len(data['total_rank']) + 1
                    rank_index0 = False
                    for data in tqdm.tqdm(
                        executor.map(fetch_page, range(n_page)),
                        total=n_page,
                        desc=f'parsing statistics paging from {domain}',
                    ):
                        if stop:
                            break
                        n_added = 0
                        for row, submissions in zip(data['total_rank'], data['submissions']):
                            handle = row.pop('user_slug').lower()
                            data_region = row.pop('data_region').lower()
                            data_domain = Statistic.DOMAINS[data_region]
                            member = f'{handle}@{data_domain}'

                            if users is not None and member not in users or member in result:
                                continue
                            row.pop('contest_id')
                            row.pop('global_ranking')

                            r = result.setdefault(member, OrderedDict())
                            r['_ranking_domain'] = domain
                            r['member'] = member
                            r['solving'] = row.pop('score')
                            r['name'] = row.pop('username')

                            rank = int(row.pop('rank'))
                            rank_index0 |= rank == 0
                            r['place'] = rank + (1 if rank_index0 else 0)

                            r['info'] = {'profile_url': {'_domain': data_domain, '_handle': handle}}

                            country = None
                            for field in 'country_code', 'country_name':
                                country = country or row.pop(field, None)
                            if country:
                                r['country'] = country

                            has_download_submissions = n_top_submissions and r['place'] <= n_top_submissions

                            skip = False
                            solved = 0
                            stats = (statistics or {}).get(handle, {})
                            problems = r.setdefault('problems', stats.get('problems', {}))
                            clear_problems_fields(problems)
                            for i, (k, s) in enumerate(submissions.items(), start=1):
                                short = problems_info[k]['short']
                                p = problems.setdefault(short, {})
                                time = datetime.fromtimestamp(s['date']) - start_time
                                p['time_in_seconds'] = time.total_seconds()
                                p['time'] = self.to_time(time)
                                if s['status'] == 10:
                                    solved += 1
                                    p['result'] = '+' + str(s['fail_count'] or '')
                                else:
                                    p['result'] = f'-{s["fail_count"]}'
                                if s.get('lang'):
                                    p['language'] = s['lang'].lower()
                                if 'submission_id' in s:
                                    if (has_download_submissions or statistics) and (
                                        'submission_id' in p and p['submission_id'] != s['submission_id']
                                        or 'language' not in p
                                    ):
                                        solutions_for_get.append(p)
                                    p['submission_id'] = s['submission_id']
                                    p['external_solution'] = True
                                    p['data_region'] = s['data_region']

                                    skip = skip or s['submission_id'] in solutions_ids
                                    solutions_ids.add(s['submission_id'])

                            if users:
                                users.remove(member)
                                if not users:
                                    stop = True

                            if not problems or skip:
                                result.pop(member)
                                continue

                            r['solved'] = {'solving': solved}
                            penalty_time = datetime.fromtimestamp(row.pop('finish_time')) - start_time
                            r['penalty'] = self.to_time(penalty_time)
                            times[member] = penalty_time

                            if get_item(row, 'user_badge.icon'):
                                row['badge'] = {
                                    'icon': urljoin(standings_url, row['user_badge']['icon']),
                                    'title': row['user_badge']['display_name'],
                                }
                                badges.add(row['badge']['title'])
                            if row.get('badge') or not row.get('user_badge'):
                                row.pop('user_badge', None)

                            r.update(row)

                            hidden_fields |= set(row.keys())
                            if statistics and member in statistics:
                                stat = statistics[member]
                                for k in ('rating_change', 'new_rating', 'raw_rating', '_rank'):
                                    if k in stat:
                                        r[k] = stat[k]
                            n_added += 1
                            parsed_domains.add(domain)

                        if n_added == 0 and not users:
                            stop = True

                fetch_ranking(domain='.com', region='global')
                fetch_ranking(domain='.cn', region='local')

                if len(parsed_domains) > 1:
                    def get_key(row):
                        return (-row['solving'], times[row['member']])
                    last = None
                    for rank, row in enumerate(sorted(result.values(), key=get_key), start=1):
                        value = get_key(row)
                        if value != last:
                            place = rank
                            last = value
                        row['place'] = place

                to_get_solutions = os.environ.get('SKIP_GET_SOLUTIONS') is None and (
                    self.contest.has_rating_prediction
                    or self.end_time + timedelta(hours=2) < now()
                )
                if solutions_for_get and to_get_solutions:
                    try:
                        if n_top_submissions:
                            n_solutions_limit = n_top_submissions * len(problems_info)
                            solutions_for_get = solutions_for_get[:n_solutions_limit]
                        fetch_submission_func = partial(Statistic.fetch_submission, raise_on_error=True)
                        for submission, data in tqdm.tqdm(
                            executor.map(fetch_submission_func, solutions_for_get),
                            total=len(solutions_for_get),
                            desc='fetching submissions',
                        ):
                            if 'code' in data:
                                submission['solution'] = data['code']
                            if 'lang' in data:
                                submission['language'] = data['lang']
                    except Exception as e:
                        LOG.warning(f'Failed to fetch submissions: {e}')

        standings = {
            'result': result,
            'url': standings_url,
            'hidden_fields': hidden_fields,
            'problems': list(problems_info.values()),
            'badges': list(sorted(badges)),
            'info_fields': ['badges'],
        }
        return standings

    @staticmethod
    def get_source_code(contest, problem):
        _, data = Statistic.fetch_submission(problem, raise_on_error=False)
        if not data:
            with REQ.with_proxy(
                time_limit=10,
                n_limit=30,
                filepath_proxies=Statistic._get_proxies_file(problem.get('data_region')),
                connect=partial(Statistic.fetch_submission, problem, raise_on_error=True),
            ) as req:
                _, data = req.proxer.get_connect_ret()
            if not data:
                return {}

        data['solution'] = data.pop('code', None)
        data['language'] = data.pop('lang', None)
        return data

    @staticmethod
    def is_china(account):
        return account.key.endswith('.cn')

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        rate_limiter = RateLimiter(max_calls=1, period=2)

        @lru_cache()
        def get_all_contests(data_region=''):
            domain = Statistic.DOMAINS[data_region]
            page = Statistic._get(
                f'https://leetcode{domain}/graphql',
                post=b'{"variables":{},"query":"{allContests{titleSlug}}"}',
                content_type='application/json',
            )
            return json.loads(page)['data']

        def fetch_profile_data(req, account, raise_on_error=False, **kwargs):
            nonlocal stop
            nonlocal global_ranking_users
            nonlocal rate_limiter

            profile_url = account.info.setdefault('profile_url', {})
            key = (profile_url['_domain'], profile_url['_handle'])
            if key in global_ranking_users:
                return account, global_ranking_users[key]
            handle = profile_url['_handle']

            if stop:
                return account, False

            # connect_func = partial(fetch_profile_data, account=account, raise_on_error=True)
            # req.proxer.set_connect_func(connect_func)

            page = False
            account_is_china = Statistic.is_china(account)
            while True:
                try:
                    with rate_limiter:
                        if account_is_china:
                            ret = {}

                            post = '''
                            {
                                "operationName":"userProfilePublicProfile",
                                "variables":{"userSlug":"''' + handle + '''"},
                                "query":"
                                query userProfilePublicProfile($userSlug: String!) {
                                  userProfilePublicProfile(userSlug: $userSlug) {
                                    haveFollowed
                                    siteRanking
                                    profile {
                                      userSlug
                                      realName
                                      aboutMe
                                      asciiCode
                                      userAvatar
                                      gender
                                      websites
                                      skillTags
                                      ipRegion
                                      birthday
                                      location
                                      useDefaultAvatar
                                      github
                                      school: schoolV2 {
                                        schoolId
                                        logo
                                        name
                                      }
                                      company: companyV2 {
                                        id
                                        logo
                                        name
                                      }
                                      job
                                      globalLocation {
                                        country
                                        province
                                        city
                                        overseasCity
                                      }
                                      socialAccounts {
                                        provider
                                        profileUrl
                                      }
                                      skillSet {
                                        langLevels {
                                          langName
                                          langVerboseName
                                          level
                                        }
                                        topicAreaScores {
                                          score
                                          topicArea {
                                            name
                                            slug
                                          }
                                        }
                                      }
                                    }
                                    educationRecordList {
                                      unverifiedOrganizationName
                                    }
                                    occupationRecordList {
                                      unverifiedOrganizationName
                                      jobTitle
                                    }
                                  }
                                }
                            "}'''
                            post = re.sub(r'\s+', ' ', post)

                            page = Statistic._get(
                                'https://leetcode.cn/graphql',
                                post=post.encode(),
                                content_type='application/json',
                                # req=req,  FIXME: enable proxy if needed
                                **kwargs,
                            )
                            profile_data = json.loads(page)
                            if profile_data['data']['userProfilePublicProfile'] is None:
                                page = None
                                break

                            ret = profile_data['data']['userProfilePublicProfile']
                            ret['profile']['slug'] = ret['profile'].pop('userSlug')

                            post = '''
                            {"operationName":"userContestRankingInfo","variables":{"userSlug":"''' + handle + '''"},"query":"
                                query userContestRankingInfo($userSlug: String!) {
                                  userContestRanking(userSlug: $userSlug) {
                                    attendedContestsCount
                                    rating
                                    globalRanking
                                    localRanking
                                    globalTotalParticipants
                                    localTotalParticipants
                                    topPercentage
                                  }
                                  userContestRankingHistory(userSlug: $userSlug) {
                                    attended
                                    rating
                                    ranking
                                    contest {
                                      title
                                      startTime
                                    }
                                  }
                                }
                            "}'''  # noqa: E501
                            post = re.sub(r'\s+', ' ', post)
                            page = Statistic._get(
                                'https://leetcode.cn/graphql/noj-go/',
                                post=post.encode(),
                                content_type='application/json',
                                # req=req,  FIXME: enable proxy if needed
                                **kwargs,
                            )
                            ranking_data = json.loads(page)
                            ret['ranking'] = ranking_data['data']['userContestRanking']
                            ret['history'] = ranking_data['data']['userContestRankingHistory']
                            page = ret
                        else:
                            profile_page = Statistic._get(
                                'https://leetcode.com/graphql',
                                post=b'''
                                {"operationName":"userPublicProfile","variables":{"username":"''' + handle.encode() + b'''"},"query":"    query userPublicProfile($username: String!) {  matchedUser(username: $username) {    username    profile {      ranking      userAvatar      realName      aboutMe      school      websites      countryName      company      jobTitle      skillTags      postViewCount      postViewCountDiff      reputation      reputationDiff      solutionCount      solutionCountDiff      categoryDiscussCount      categoryDiscussCountDiff    }  }}    "
}''',  # noqa: E501
                                content_type='application/json',
                            )
                            profile_data = json.loads(profile_page)
                            user_does_not_exist = any([
                                'user does not exist' in e['message']
                                for e in profile_data.get('errors', [])
                            ])
                            if user_does_not_exist:
                                page = None
                                break
                            ret = profile_data['data']['matchedUser']
                            ret['profile']['slug'] = ret.pop('username')

                            contest_page = Statistic._get(
                                'https://leetcode.com/graphql',
                                post=b'''
                                {"operationName":"getContentRankingData","variables":{"username":"''' + handle.encode() + b'''"},"query":"query getContentRankingData($username: String!) {  userContestRanking(username: $username) {  attendedContestsCount    rating    globalRanking    __typename  }  userContestRankingHistory(username: $username) {    contest {      title      startTime      __typename    }   rating    ranking    attended    __typename  }}"}''',  # noqa: E501
                                content_type='application/json',
                            )
                            contest_data = json.loads(contest_page)['data']
                            ret['ranking'] = contest_data['userContestRanking']
                            ret['history'] = contest_data['userContestRankingHistory']
                            page = ret
                    break
                except FailOnGetResponse as e:
                    code = e.code
                    if code == 404:
                        page = None
                        break

                    page = False
                    if code in [403, 429]:
                        stop = True
                    break
                    # if account_is_china:
                    #     if raise_on_error:
                    #         raise e

                    #     ret = req.proxer.get_connect_ret()
                    #     if ret:
                    #         return ret
                    # else:
                    #     page = False
                    #     if code in [403, 429]:
                    #         stop = True
                    #     break
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
                        'https://leetcode.cn/graphql',
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

        with REQ.with_proxy(
            time_limit=10,
            n_limit=30,
            inplace=False,
            filepath_proxies=os.path.join(os.path.dirname(__file__), '.leetcode.proxies'),
        ) as req, PoolExecutor(max_workers=8) as executor:
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
                            data_domain = Statistic.DOMAINS[data_region]
                            username = node['user']['profile']['userSlug'].lower()
                            global_ranking_users[(data_domain, username)] = {
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
            for account, page in executor.map(fetch_profile_data_func, accounts):
                if pbar:
                    pbar.set_postfix(stop=stop)
                    pbar.update()

                if not page:
                    if page is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                contest_addition_update_by = None
                ratings, rankings, contest_keys = [], [], []

                info = page.pop('profile')
                if info is None or info.get('slug') == 'deleted_user':
                    yield {'delete': True}
                    continue
                history = page.pop('history') or []
                info.update(page.pop('ranking') or {})

                contest_addition_update_by = 'start_time'
                for h in history:
                    if not h['attended']:
                        continue
                    rankings.append(h['ranking'])
                    ratings.append(h['rating'])
                    start_time = h['contest']['startTime']
                    start_time = datetime_from_timestamp(start_time)
                    contest_keys.append(start_time)

                for k in ('profile_url', ):
                    if k in account.info:
                        info[k] = account.info[k]

                contest_addition_update = {}
                last_rating = None
                for rating, ranking, contest_key in zip(ratings, rankings, contest_keys):
                    if not ranking:
                        continue
                    int_rating = round(rating)
                    update = contest_addition_update.setdefault(contest_key, OrderedDict())
                    update['rating_change'] = int_rating - last_rating if last_rating is not None else None
                    update['new_rating'] = int_rating
                    update['raw_rating'] = rating
                    update['_rank'] = ranking
                    if Statistic.is_china(account):
                        update['_rank_field'] = 'addition___rank'
                    last_rating = int_rating
                if last_rating and 'rating' not in info:
                    info['rating'] = last_rating
                if account.key.startswith('@_deleted_user_'):
                    info['rating'] = None

                if 'global_ranking' in info:
                    global_ranking = int(re.split('[^0-9]', str(info['global_ranking']))[0])
                elif 'globalRanking' in info:
                    global_ranking = info['globalRanking']
                else:
                    global_ranking = None
                if global_ranking:
                    info['global_ranking'] = global_ranking
                    page = (int(global_ranking) + 24) // 25
                    info['global_ranking_page'] = page

                ret = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': contest_addition_update,
                        'by': contest_addition_update_by,
                        'clear_rating_change': True,
                        'try_renaming_check': True,
                        'try_fill_missed_ranks': True,
                    },
                }

                profile_url = account.info.setdefault('profile_url', {})
                handle = profile_url['_handle']
                assert info and info['slug'].lower() == handle, \
                    f'Account handle {handle} should be equal username {info["slug"]}'

                yield ret

    @transaction.atomic()
    @staticmethod
    def update_submissions(account, resource):
        info = deepcopy(account.info.setdefault('submissions_', {}))
        leetcode_session = account.info.get('variables_', {}).get('LEETCODE_SESSION', None)
        if leetcode_session:
            leetcode_session_hash = hashlib.md5(leetcode_session['value'].encode()).hexdigest()
            if info.get('leetcode_session_hash') != leetcode_session_hash:
                info['leetcode_session_hash'] = leetcode_session_hash
                info.pop('submission_id', None)
        last_submission_id = info.setdefault('submission_id', -1)

        profile_url = account.info.setdefault('profile_url', {})
        handle = profile_url['_handle']

        def recent_accepted_submissions(req=REQ):

            if Statistic.is_china(account):
                post = '''
                {"query":"query recentAcSubmissions($userSlug: String!) { recentACSubmissions(userSlug: $userSlug) { submissionId submitTime question { title translatedTitle titleSlug questionFrontendId } } } ","variables":{"userSlug":"''' + handle + '''"},"operationName":"recentAcSubmissions"}
                '''  # noqa: E501
                page = Statistic._get(
                    'https://leetcode.cn/graphql/noj-go/',
                    content_type='application/json',
                    post=post.encode(),
                    req=req,
                )
                data = json.loads(page)['data']['recentACSubmissions']
            else:
                post = '''
                {"query":"query recentAcSubmissions($username: String!, $limit: Int!) { recentAcSubmissionList(username: $username, limit: $limit) { id title titleSlug timestamp } } ","variables":{"username":"''' + handle + '''","limit":20},"operationName":"recentAcSubmissions"}
                '''  # noqa: E501
                page = Statistic._get(
                    'https://leetcode.com/graphql',
                    content_type='application/json',
                    post=post.encode(),
                    req=req,
                )
                data = json.loads(page)['data']['recentAcSubmissionList']
            return data

        ret = defaultdict(int)
        save_account = False
        wrong_problems = set()

        @suppress_db_logging_context()
        @RateLimiter(max_calls=20, period=60)
        def process_submission(submissions, with_last_submission=True, status_raise_not_found=True):
            nonlocal ret
            nonlocal save_account
            for submission in submissions:

                def get_field(*fields, raise_not_found=True):
                    for field in fields:
                        if field in submission:
                            return submission.pop(field)
                    if raise_not_found:
                        raise KeyError(f'No field {fields} in {submission}')

                if 'question' in submission:
                    submission.update(submission.pop('question'))
                submission_time = int(get_field('timestamp', 'submitTime'))
                submission_id = get_field('id', 'submissionId')
                if submission_id is None:
                    continue
                submission_id = int(submission_id)
                status_display = get_field('status', raise_not_found=status_raise_not_found)
                is_accepted = status_display in {None, 10}

                if with_last_submission and submission_id <= last_submission_id:
                    return False

                title_slug = get_field('titleSlug', 'title_slug')
                if title_slug in wrong_problems:
                    continue

                regex = '/' + re.escape(title_slug) + '/?$'
                qs = resource.problem_set.filter(url__regex=regex)
                problems = qs[:2]
                if len(problems) != 1:
                    LOG.warning(f'Wrong problems = {problems} for title slug = {title_slug}')
                    if not problems:
                        ret['n_missing_problem'] += 1
                    else:
                        ret['n_many_problems'] += 1
                    wrong_problems.add(title_slug)
                    continue
                problem = problems[0]
                contests = set(problem.contests.all()[:2])
                if problem.contest:
                    contests.add(problem.contest)
                if len(contests) != 1:
                    LOG.warning(f'Wrong contests = {contests} for problem = {problem}')
                    ret['n_missing_contest'] += 1
                    wrong_problems.add(title_slug)
                    continue
                contest = next(iter(contests))
                short = problem.short

                title = get_field('title')
                if problem.name != title:
                    LOG.warning(f'Problem {problem} has wrong name: {title} vs {problem.name}')
                    ret['n_wrong_problem_name'] += 1
                    wrong_problems.add(title_slug)
                    continue

                if with_last_submission and submission_id > info['submission_id']:
                    info['submission_id'] = submission_id
                    save_account = True

                submission = dict(
                    binary=is_accepted,
                    result='+' if is_accepted else '-',
                    submission_id=submission_id,
                    submission_time=submission_time,
                )

                stat, _ = create_upsolving_statistic(contest=contest, account=account)
                problems = stat.addition.setdefault('problems', {})
                problem = problems.setdefault(short, {})
                if not is_improved_solution(submission, problem):
                    ret['n_already_solved'] += 1
                    continue

                upsolving = problem.setdefault('upsolving', {})
                if not is_improved_solution(submission, upsolving):
                    ret['n_already_upsolving'] += 1
                    continue

                problem['upsolving'] = submission
                ret['n_updated'] += 1
                stat.save()

                submission_time = datetime.fromtimestamp(submission_time).replace(tzinfo=pytz.utc)
                if not account.last_submission or account.last_submission < submission_time:
                    account.last_submission = submission_time
                    save_account = True
            return True

        submissions = recent_accepted_submissions()
        process_submission(submissions, with_last_submission=False, status_raise_not_found=False)

        if leetcode_session and not leetcode_session.get('disabled'):
            req = copy.copy(REQ)
            req.cookie_filename = None
            req.init_opener()
            req.add_cookie('LEETCODE_SESSION', leetcode_session['value'], domain='.leetcode.com')
            offset = info.pop('offset', 0)
            limit = 20
            info.pop('error', None)
            while True:
                url = Statistic.API_SUBMISSIONS_URL_FORMAT_.format(offset, limit)
                try:
                    submissions_page = Statistic._get(url, req=req, n_attempts=5)
                except FailOnGetResponse as e:
                    if e.code == 401:
                        leetcode_session['disabled'] = True
                        save_account = True
                    info['error'] = str(e)
                    info['offset'] = offset
                    info['submission_id'] = last_submission_id
                    break
                submissions_data = json.loads(submissions_page)
                submissions = submissions_data['submissions_dump']
                need_more = process_submission(submissions)
                if not need_more or not submissions_data['has_next']:
                    break
                offset += limit

        if save_account:
            account.info['submissions_'] = info
            account.save(update_fields=['info', 'last_submission'])
        return ret
