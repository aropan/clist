# -*- coding: utf-8 -*-

import os
import re
import json
import shlex
from collections import OrderedDict
from urllib.parse import urljoin

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from utils.timetools import parse_datetime
from clist.templatetags.extras import get_item


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):

        slug = self.url.rstrip('/').rsplit('/', 1)[-1]
        api_standings_url = urljoin(self.url, f'/api/v1/contest/{slug}/public-ranking')
        try:
            data = REQ.get(api_standings_url, return_json=True)
        except FailOnGetResponse as e:
            if 'Contest not found' in e.response:
                return {'action': 'delete'}
            raise e

        parse_info = get_item(data, 'data.ranking.frozenRanklistJson.contest')

        problems_infos = OrderedDict()
        problem_stats = get_item(data, 'data.ranking.frozenRanklistJson.problemStats')
        for problem_key, problem_stat in sorted(problem_stats.items(), key=lambda x: x[1]['problemAlphabet']):
            problem_info = {
                'short': problem_stat['problemAlphabet'],
                'name': problem_stat['formattedProblemTitleStr'],
                'code': problem_stat['contestProblemId'],
            }
            problems_infos[problem_key] = problem_info

        result = OrderedDict()

        total = get_item(data, 'data.ranking.frozenRanklistJson.total')
        per_page = get_item(data, 'data.ranking.frozenRanklistJson.perPage')
        n_pages = (total - 1) // per_page + 1
        for page in range(n_pages):
            if page:
                data = REQ.get(api_standings_url, params={'page': page + 1}, return_json=True)

            ranks = get_item(data, 'data.ranking.frozenRanklistJson.ranks')
            for r in ranks:
                kind = 'user' if 'userData' in r else 'team'
                is_team = kind == 'team'
                user_data = r.pop(f'{kind}Data')
                problem_stats = r.pop('problemStat')
                if not problem_stats:
                    continue
                handle = user_data[f'{kind}Id']
                if is_team:
                    handle = f'team-{handle}'
                if handle in result:
                    continue
                row = result.setdefault(handle, {'member': handle})
                row['name'] = user_data.pop(f'{kind}NameStr')
                row['place'] = r.pop('rank')
                row['solving'] = r.pop('totalSolved')
                row['penalty'] = r.pop('score')

                info = row.setdefault('info', {})
                info['profile_url'] = {'slug': user_data.pop(f'{kind}HandleStr'), 'kind': kind}
                info['is_team'] = is_team

                last_accepted_at = r.pop('lastAcceptedAt')
                if last_accepted_at:
                    row['_last_submit_time'] = int(parse_datetime(last_accepted_at).timestamp())

                last_tried_at = r.pop('lastTriedAt')
                if last_tried_at:
                    row['_last_tried_time'] = int(parse_datetime(last_tried_at).timestamp())

                problems = row.setdefault('problems', {})
                for problem_key, problem_stat in problem_stats.items():
                    short = problems_infos[problem_key]['short']
                    problem = problems.setdefault(short, {})
                    is_accepted = problem_stat.pop('isSolved')
                    attempts = problem_stat.pop('numOfTriesBeforeAC')

                    time = problem_stat.pop('solvedAt', None)
                    if not time:
                        time = problem_stat.pop('lastTriedAt', None)
                    if time:
                        time = (parse_datetime(time) - self.start_time).total_seconds()
                        problem['time'] = self.to_time((time - 1) // 60 + 1, 2)

                    if is_accepted:
                        problem['result'] = '+' if attempts == 0 else f'+{attempts}'
                        if time:
                            problem['time_in_seconds'] = time
                    else:
                        problem['result'] = f'-{attempts}'

        standings = {
            'url': os.path.join(self.url, 'ranklist'),
            'result': result,
            'problems': list(problems_infos.values()),
            'info_fields': ['parse'],
            'parse': parse_info,
            'standings_kind': parse_info['contestTypeStr'],
        }

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_profile_data(account):
            url = resource.profile_url.format(**account.dict_with_info())
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 500:
                    return None
                raise e

            match = re.search(
                r'''
                function\((?P<params>[^\)]*)\)\s*{\s*return\s*(?P<data>\{.*\})\}\((?P<values>.*)\)\);
                ''',
                page,
                re.VERBOSE,
            )
            raw_data = match.group('data')
            raw_data = re.sub(r'(?<=\{|\,|\:)([a-zA-Z_][a-zA-Z0-9_]*)(?=\:)', r'"\1"', raw_data)

            params = match.group('params').split(',')

            lexer = shlex.shlex(match.group('values'), posix=True)
            lexer.whitespace = ','
            lexer.whitespace_split = True
            lexer.quotes = '"'
            values = list(lexer)

            for param, value in zip(params, values):
                raw_data = re.sub(r'(?<=\:|\[)' + param + r'(?=\,|\}|\])', f'"{value}"', raw_data)

            data = json.loads(raw_data)
            kind = account.info['profile_url']['kind']
            data = data['data'][0][kind]

            return data, kind

        with PoolExecutor(max_workers=8) as executor:
            for data_kind in executor.map(fetch_profile_data, accounts):
                if pbar:
                    pbar.update()

                if data_kind is None:
                    yield {'skip': True}
                    continue

                data, kind = data_kind
                info = {}
                for field, path in (
                    ('name', f'{kind}NameStr'),
                    ('country', 'countryInformation.name'),
                    ('institution', 'institution.institutionNameStr'),
                    ('avatar_url', f'{kind}AvatarStr'),
                    ('created_at', 'created_at'),
                    ('last_logged_at', 'lastLoggedTimestamp'),
                    ('about_me', 'shortBioStr'),
                ):
                    value = get_item(data, path)
                    if value and len(value) > 1 and value != "null":
                        info[field] = value
                ret = {'info': info}
                members = data.pop('members', None)
                if members:
                    info['members'] = [
                        {'slug': member['user']['userHandleStr'], 'name': member['user']['userNameStr']}
                        for member in members
                    ]
                yield ret
