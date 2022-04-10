#!/usr/bin/env python3

import json
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        total_pages = None
        curr_page = 0
        result = {}

        page = REQ.get('https://api.sort-me.org/getArchiveById?id=1')
        data = json.loads(page)
        for season in data['seasons']:
            if str(season['source_contest']) == self.key:
                tasks = season['tasks']
                break
        else:
            tasks = None

        problems_info = OrderedDict()
        if tasks is not None:
            for idx, task in enumerate(season['tasks']):
                short = chr(ord('A') + idx)
                problems_info[short] = {
                    'key': str(task['id']),
                    'name': task['name'],
                    'short': short,
                    'url': f'https://sort-me.org/tasks/{task["id"]}',
                    'full_score': 100,
                }

        while total_pages is None or curr_page < total_pages:
            curr_page += 1
            url = f'https://api.sort-me.org/getContestTable?contestid={self.key}&page={curr_page}'
            page = REQ.get(url)
            data = json.loads(page)

            total_pages = data['pages']
            for r in data['table']:
                handle = str(r.pop('uid'))
                row = result.setdefault(handle, OrderedDict(member=handle))
                row['place'] = r.pop('place')
                row['solving'] = r.pop('sum')
                row['name'] = r.pop('login')

                avatar = r.pop('avatar')
                if avatar:
                    row.setdefault('info', {})['avatar'] = avatar

                problems = row.setdefault('problems', {})
                for idx, (score, time) in enumerate(r.pop('results')):
                    if score == -1 and time == 0:
                        continue
                    short = chr(ord('A') + idx)
                    full_score = problems_info.setdefault(short, {'short': short}).setdefault('full_score', 100)
                    problems[short] = {
                        'result': score,
                        'time': self.to_time(time, num=2),
                        'partial': score < full_score,
                    }
                if not problems:
                    result.pop(handle)

        standings = {
            'result': result,
            'url': self.standings_url or f'https://sort-me.org/tasks/result?archive=1&result={self.key}',
            'problems': list(problems_info.values()),
        }

        return standings
