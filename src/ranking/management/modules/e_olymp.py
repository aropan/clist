#!/usr/bin/env python

import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from ratelimiter import RateLimiter

from clist.templatetags.extras import normalize_field
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    API_URL = 'https://api.eolymp.com/spaces/00000000-0000-0000-0000-000000000000/graphql'
    DEFAULT_PICTURE = 'https://static.eolymp.com'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = self.url.rstrip('/') + '/scoreboard'

        contest_info_query = '''
query GetContestInfo($id: ID!) {
  contest(id: $id, extra: ["STAFF"]) {
    scoring  { showScoreboard attemptPenalty freezingTime allowUpsolving tieBreaker }
    scoreboard(roundId: $id) { visibility columns { id type title } }
    staff { edges { node { id } role displayName } }
  }
}
        '''
        data = {'query': contest_info_query, 'variables': {'id': self.key}}
        data = REQ.get(self.API_URL, post=json.dumps(data), return_json=True)
        for error in data.get('errors', []):
            if 'code = Unauthenticated' in error['message']:
                raise ExceptionParseStandings('Unauthorized access')
            if 'code = NotFound' in error['message']:
                raise ExceptionParseStandings('Contest not found')

        scoring = data['data']['contest']['scoring']
        scoreboard = data['data']['contest']['scoreboard']
        if scoreboard['visibility'] not in {'PUBLIC', 'UNKNOWN_VISIBILITY'}:
            return {'action': 'skip', 'url': standings_url}
        columns = scoreboard['columns']
        problems_info = OrderedDict()
        for column in columns:
            if column['type'] != 'PROBLEM_SCORE':
                continue
            problem = {
                'code': column['id'],
                'short': column['title'],
            }
            problems_info[problem['code']] = problem

        writers = []
        for staff in data['data']['contest']['staff']['edges']:
            if staff["role"] in {"AUTHOR", "COORDINATOR"}:
                writers.append(staff['node']['id'])

        scoreboard_query = '''
query GetScoreboard($id: ID!, $first: Int, $offset: Int) {
  contest(id: $id) {
    scoreboard(roundId: $id) {
      rows(first: $first, offset: $offset) {
        nodes {
          member {
            id
            account {
              ... on CommunityUser { nickname picture country { name } }
              ... on CommunityTeam { name members { id account { ... on CommunityUser { nickname } } } }
            }
          }
          values { columnId ... on ContestScoreboardProblemScore { score penalty attempts time percentage } }
          rank rankLength score penalty tieBreaker unofficial disqualified medal
        }
        pageInfo {
          hasNextPage
        }
      }
    }
  }
}
'''
        offset = 0
        result = {}
        while True:
            data = {'query': scoreboard_query, 'variables': {'id': self.key, 'first': 100, 'offset': offset}}
            data = REQ.get(self.API_URL, post=json.dumps(data), return_json=True)
            data = data['data']['contest']['scoreboard']['rows']
            if not data:
                raise ExceptionParseStandings('No scoreboard data')
            for row in data['nodes']:
                offset += 1
                member = row.pop('member')
                if member is None:
                    continue
                member_id = member['id']
                handle = member['account']['nickname']
                r = result.setdefault(member_id, {'member': member_id})
                info = r.setdefault('info', {})
                r['name'] = handle
                info['profile_url'] = {'account': handle}
                country = member['account']['country']
                if country:
                    r['country'] = country['name']
                picture = member['account']['picture']
                if picture and picture != self.DEFAULT_PICTURE:
                    info['picture'] = picture
                r['place'] = row.pop('rank')
                r['solving'] = row.pop('score')
                r['unofficial'] = row.pop('unofficial')
                r['disqualified'] = row.pop('disqualified')
                if r['unofficial'] or r['disqualified']:
                    r.pop('place')
                    r['_no_update_n_contests'] = True
                if scoring['attemptPenalty']:
                    r['penalty'] = row.pop('penalty')
                problems = r.setdefault('problems', {})
                for values in row.pop('values'):
                    code = values['columnId']
                    if code not in problems_info:
                        continue
                    problem = problems.setdefault(problems_info[code]['short'], {})
                    if self.contest.kind == 'IOI':
                        problem['result'] = values['score']
                        problem['attempts'] = values['attempts']
                        if values['percentage'] and values['percentage'] != 1:
                            problem['partial'] = True
                    else:
                        problem['result'] = '+' if values['score'] else '-'
                        if values['attempts']:
                            problem['result'] += str(values['attempts'])
                    if values['time']:
                        values['time_in_seconds'] = values['time']
                        problem['time'] = self.to_time(values['time'] // 60, 2)
                to_clear = not problems and r['solving'] == 0
                stats = (statistics or {}).get(member_id, {})
                for field in 'new_rating', 'rating_change', 'old_rating', 'level':
                    if field in stats and field not in r:
                        r[field] = stats[field]
                        to_clear = False
                if to_clear:
                    result.pop(member_id)
            if not data['pageInfo']['hasNextPage']:
                break

        standings = {
            'url': standings_url,
            'result': result,
            'hidden_fields': ['unofficial', 'disqualified'],
            'problems': list(problems_info.values()),
        }
        if writers:
            standings['writers'] = writers
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=10, period=1)
        def fetch_profile(user, account):
            if account.info.get('is_team') or account.info.get('_no_profile_url'):
                return False

            info = {}
            return_data = {'info': info}
            if account.name:
                member_id = account.key
            elif re.match('^[a-z0-9]{26}$', account.key):
                member_id = account.key
            else:
                url = resource.profile_url.format(**account.dict_with_info())
                page = REQ.get(url)
                match = re.search(r'typename\\":\\"CommunityMember\\",\\"id\\":\\"(?P<id>[^"]+)\\"', page)
                if not match:
                    return False
                member_id = match.group('id')
                if member_id != account.key:
                    return_data['rename'] = member_id

            profile_query = '''
query Profile($id: ID!) {
  member(id: $id) {
    picture displayName createdAt inactive unofficial rank rating level
    stats {
      streak problemsSolved submissionsTotal submissionsAccepted
    }
    account {
      ... on CommunityUser {
        nickname name country { name } city
      }
    }
  }
}
            '''
            data = {'query': profile_query, 'variables': {'id': member_id}}
            data = REQ.get(Statistic.API_URL, post=json.dumps(data), return_json=True)
            data = data['data']['member']
            account_data = data.pop('account')
            country = account_data.pop('country')
            if country:
                info['country'] = country['name']
            info['name'] = account_data.pop('nickname')
            if full_name := account_data.pop('name'):
                info['full_name'] = full_name
            picture = data.pop('picture')
            if picture and picture != Statistic.DEFAULT_PICTURE:
                info['picture'] = picture

            data.update(data.pop('stats'))
            data.update(account_data)
            for field in ('rank', 'rating', 'level', 'city'):
                if value := data.pop(field, None):
                    info[field] = value
            info['extra'] = {normalize_field(k): v for k, v in data.items()}
            info['profile_url'] = {'account': info['name']}

            perfomance_query = '''
query Performance($id: ID!, $first: Int, $offset: Int) {
  performance(memberId: $id, first: $first, offset: $offset) {
    nodes { contestId value level }
    pageInfo { hasNextPage }
  }
}
            '''
            offset = 0
            rating_updates = {}
            while True:
                data = {'query': perfomance_query, 'variables': {'id': member_id, 'first': 100, 'offset': offset}}
                data = REQ.get(Statistic.API_URL, post=json.dumps(data), return_json=True)
                data = data['data']['performance']
                prev_rating = None
                for node in data['nodes']:
                    offset += 1
                    contest_id = node.pop('contestId')
                    rating = node.pop('value')
                    rating_update = rating_updates.setdefault(contest_id, {})
                    rating_update['level'] = node.pop('level')
                    rating_update['new_rating'] = rating
                    if prev_rating is not None:
                        rating_update['rating_change'] = rating - prev_rating
                        rating_update['old_rating'] = prev_rating
                    prev_rating = rating
                if not data['pageInfo']['hasNextPage']:
                    break
            return_data['contest_addition_update_params'] = {
                'update': rating_updates,
                'by': 'key',
                'clear_rating_change': True,
            }

            return return_data

        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_profile, users, accounts):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue
                yield data
