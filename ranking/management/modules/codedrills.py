#!/usr/bin/env python

import base64
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from pprint import pprint  # noqa

import blackboxprotobuf

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = f'{self.url.rstrip("/")}/leaderboard'

    def get_standings(self, users=None, statistics=None):

        slug = self.url.split('/')[-1]
        per_page = 100

        def to_list(value):
            return value if isinstance(value, list) else [value]

        def get_by_key(message, key):
            ret = None
            for k, v in list(message.items()):
                if k == key or k.startswith(f'{key}-'):
                    if ret is None:
                        ret = v
                    else:
                        ret = to_list(ret) + to_list(v)
                    message.pop(k)
            return ret

        def rec_fix_type(messages, types, path=[]):
            if not types:
                return
            for message in to_list(messages):
                to_conv = True
                a = []
                for k, v in types.items():
                    a.append(v['type'])
                    if not v['type'].startswith('fixed'):
                        to_conv = False
                        break

                if to_conv:
                    raise ExceptionParseStandings(f'Excepted str value for path = {path}')
                else:
                    for k, v in types.items():
                        if k in message:
                            rec_fix_type(message[k], v.get('message_typedef'), path + [k])

        def get_response(url, message, types, force_str_paths=(), xmessage_type=None):
            query = blackboxprotobuf.encode_message(message, types)
            query = len(query).to_bytes(5, byteorder='big') + query
            query = base64.b64encode(query)
            page = REQ.get(url,
                           post=query,
                           content_type='application/grpc-web-text',
                           headers={'accept': 'application/grpc-web-text'})

            data = base64.b64decode(page)
            size = int.from_bytes(data[:5], 'big')
            data = data[5:5 + size]

            message_type = {}
            for path in force_str_paths:
                d = message_type
                *path, key = path
                for k in path:
                    d = d.setdefault(k, {'type': 'message', 'message_typedef': {}})
                    d = d['message_typedef']
                d[key] = {'type': 'bytes'}

            message, types = blackboxprotobuf.decode_message(data, message_type)
            return message, types

        def get_contest_info():
            url = 'https://api.prod.codedrills.io/site/io.codedrills.proto.site.ContentViewService/GetContentView'
            message = {'1': {'2': {'1': 3, '2': slug.encode('utf-8')}}}
            types = {'1': {'type': 'message',
                           'message_typedef': {'2': {'type': 'message',
                                                     'message_typedef': {'1': {'type': 'int', 'name': ''},
                                                                         '2': {'type': 'bytes', 'name': ''}},
                                                     'name': ''}},
                           'name': ''}}
            message, types = get_response(url, message, types)
            return message

        def get_page(page=0):
            url = 'https://api.prod.codedrills.io/site/io.codedrills.proto.site.ContentViewService/GetContestScoreboard'
            message = {'1': {'2': {'1': 3, '2': slug.encode('utf8')}}, '3': {'1': page, '2': per_page}}
            types = {'1': {'message_typedef':
                           {'2': {'message_typedef':
                                  {'1': {'name': '', 'type': 'int'},
                                   '2': {'name': '', 'type': 'bytes'}},
                                  'name': '', 'type': 'message'}},
                           'name': '', 'type': 'message'},
                     '3': {'message_typedef': {'1': {'name': '', 'type': 'int'},
                                               '2': {'name': '', 'type': 'int'}},
                           'name': '', 'type': 'message'}}
            paths = [
                ['1', '1', '1', '5', '3'],
                ['1', '1', '1', '5', '4'],
                ['1', '2', '2', '1'],
                ['1', '2', '2', '2'],
                ['1', '2', '2', '4'],
                ['1', '2', '8', '2'],
                ['1', '2', '8', '3'],
                ['1', '2', '8', '4', '1'],
                ['1', '2', '8', '4', '2'],
                ['1', '2', '8', '4', '3'],
            ]
            message, types = get_response(url, message, types, force_str_paths=paths)
            rec_fix_type(message, types)
            return message

        result = {}

        def get_problems(message):
            problems = OrderedDict()
            for idx, p in enumerate(to_list(message['1']['1']['1'])):
                p = p['5']
                problem = {
                    'name': p.pop('3').decode('utf8'),
                    'code': str(p.pop('1')),
                    'short': chr(ord('A') + idx),
                    'url': self.host + 'problems/' + p.pop('4').decode('utf8'),
                }
                for label in to_list(p['11'].pop('2')):
                    label = label.decode('utf8')
                    if '/' not in label:
                        continue
                    key, val = label.split('/', 2)
                    if key == 'topics':
                        problem.setdefault('tags', []).append(val.replace('_', ' '))
                problems[problem['code']] = problem
            return problems

        def process_page(message):
            for r in to_list(message['1']['2']):
                team_info = get_by_key(r, '8')
                if team_info:
                    party = []
                    members = team_info.setdefault('members', [])
                    for m in to_list(get_by_key(team_info, '4')):
                        member = get_by_key(m, '1')
                        name = get_by_key(m, '2')
                        if not member:
                            continue
                        d = deepcopy(r)
                        d['1'] = member
                        d['2'] = name
                        d['handle'] = get_by_key(m, '3')
                        party.append(d)
                        member = {'account': member.decode('utf8')}
                        if name and isinstance(name, bytes):
                            member['name'] = name.decode('utf8')
                        members.append(member)
                else:
                    user_info = get_by_key(r, '2')
                    r['2'] = get_by_key(user_info, '2')
                    r['handle'] = get_by_key(user_info, '4')
                    party = [r]

                for r in party:
                    if not r.get('1'):
                        continue
                    member = r.pop('1').decode('utf8')
                    row = result.setdefault(member, {'member': member})

                    name = r.pop('2')
                    if name:
                        row['name'] = name.decode('utf8')

                    info = row.setdefault('info', {})
                    handle = r.pop('handle')
                    if handle:
                        info['profile_url'] = {'handle': handle.decode('utf8')}
                        info['_no_profile_url'] = False
                    else:
                        info['_no_profile_url'] = True

                    if team_info:
                        row['_field_update_name'] = '_account_name'
                        if 'name' in row:
                            row['_account_name'] = row.pop('name')

                        row['team_id'] = team_info['1']
                        name = team_info.get('2')
                        if name:
                            row['name'] = name.decode('utf8')
                        organization = team_info.get('3')
                        if organization:
                            row['organization'] = organization.decode('utf8')

                        if '5' in team_info and '4' in team_info['5']:
                            contest_slug = team_info['5']['4'].decode('utf8')
                            row['_account_url'] = self.host + f'contests/{contest_slug}/teams/{row["team_id"]}'
                        else:
                            row['_account_url'] = self.url.rstrip('/') + f'/teams/{row["team_id"]}'
                        row['_members'] = team_info['members']

                    row['place'] = r.pop('3')
                    row['solving'] = 0

                    problems = row.setdefault('problems', {})
                    penalty = 0

                    for p in to_list(r.pop('6')):
                        short = problems_info[str(p.pop('1'))]['short']
                        problem = problems.setdefault(short, {})
                        attempt = p.pop('2')
                        time = p.pop('6', None)
                        if time is not None:
                            problem['result'] = '+' if attempt == 1 else f'+{attempt - 1}'
                            problem['time'] = self.to_time(time, num=3)
                            row['solving'] += 1
                            penalty += time + attempt_penalty * (attempt - 1)
                        else:
                            problem['result'] = f'-{attempt}'
                        if '7' in p:
                            solution_id = p.pop('7')['1']
                            problem['url'] = f'{self.host}submissions/{solution_id}'
                    row['penalty'] = self.to_time(penalty, num=3)

        contest_info = get_contest_info()
        match = re.search(r'(?P<val>[0-9]+)\s+minutes?(?:\s+penalty|\.)', str(contest_info))
        attempt_penalty = int(match.group('val')) * 60 if match else 0

        message = get_page()
        problems_info = get_problems(message)

        process_page(message)

        with PoolExecutor(max_workers=4) as executor:
            n_pages = (message['2']['2'] - 1) // per_page + 1
            for message in executor.map(get_page, range(1, n_pages)):
                process_page(message)

        standings = {
            'result': result,
            'standings_url': self.url.rstrip('/') + '/scoreboard',
            'problems': list(problems_info.values()),
            'hidden_fields': ['organization'],
            'options': {'timeline': {'attempt_penalty': attempt_penalty}},
        }
        return standings
