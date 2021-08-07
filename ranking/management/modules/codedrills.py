#!/usr/bin/env python

import base64
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from pprint import pprint  # noqa

import blackboxprotobuf

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = f'{self.url.rstrip("/")}/leaderboard'

    def get_standings(self, users=None, statistics=None):
        url = 'https://api.prod.codedrills.io/site/io.codedrills.proto.site.ContentViewService/GetContestScoreboard'

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

        def get_page(page=0):
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
            message, types = blackboxprotobuf.decode_message(data)
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
                        handle = m.get('1')
                        name = m.get('2')
                        if not handle:
                            continue
                        d = deepcopy(r)
                        d['1'] = handle
                        d['2'] = name
                        party.append(d)
                        member = {'account': handle.decode('utf8')}
                        if name and isinstance(name, bytes):
                            member['name'] = name.decode('utf8')
                        members.append(member)
                else:
                    r['2'] = r['2'].get('2')
                    party = [r]

                for r in party:
                    if not r.get('1'):
                        continue
                    handle = r.pop('1').decode('utf8')
                    row = result.setdefault(handle, {'member': handle})

                    name = r.pop('2')
                    if name and isinstance(name, bytes):
                        row['name'] = name.decode('utf8')

                    if team_info:
                        row['_field_update_name'] = '_account_name'
                        if 'name' in row:
                            row['_account_name'] = row.pop('name')

                        row['team_id'] = team_info['1']
                        if not isinstance(team_info['2'], dict):
                            row['name'] = team_info['2'].decode('utf8')
                        organization = team_info.get('3')
                        if organization and isinstance(organization, bytes):
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
                            problem['result'] = '+' if attempt == 1 else f'+{attempt}'
                            problem['time'] = self.to_time(time, num=3)
                            row['solving'] += 1
                            penalty += time
                        else:
                            problem['result'] = f'-{attempt}'
                        if '7' in p:
                            solution_id = p.pop('7')['1']
                            problem['url'] = f'{self.host}submissions/{solution_id}'
                    row['penalty'] = self.to_time(penalty, num=3)

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
        }
        return standings
