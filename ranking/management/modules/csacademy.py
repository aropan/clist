# -*- coding: utf-8 -*-

from common import BaseModule, requester, LOG

import json
from pprint import pprint


class Statistic(BaseModule):
    CONTEST_STATE_ = '{0.url}'
    STANDING_URL_ = '{0.url}scoreboard/'
    SCOREBOARD_STATE_URL_ = 'https://csacademy.com/contest/scoreboard_state/?contestId={0.cid}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = int(self.key)

    def get_standings(self, users=None):
        req = requester.requester(headers=[('X-Requested-With', 'XMLHttpRequest')])
        req.caching = None
        req.time_out = 17

        url = self.CONTEST_STATE_.format(self)
        state = json.loads(req.get(url))['state']
        tasks = {}
        for task in state['contesttask']:
            tasks[task['id']] = task

        url = self.SCOREBOARD_STATE_URL_.format(self)
        state = json.loads(req.get(url))['state']
        users = {}
        for user in state['publicuser']:
            users[user['id']] = user

        result = {}
        n_total = 0
        rows = state['contestuser']
        for row in rows:
            users[user['id']] = user
            if row['contestId'] != self.cid or 'rank' not in row:
                continue
            u = users[row['userId']]
            handle = u['username']
            if not handle:
                continue
            n_total += 1
            r = result.setdefault(handle, {})
            r['member'] = handle
            r['place'] = row['rank']
            r['penalty'] = int(round(row['penalty']))
            r['solving'] = row['totalScore']
            problems = r.setdefault('problems', {})
            solving = 0
            for k, v in row['scores'].items():
                task = tasks[int(k)]
                letter = chr(64 + task['contestIndex'])
                p = problems.setdefault(letter, {})
                p['name'] = task['longName']
                p['result'] = v['score']
                if v['score'] > 0:
                    solving += 1
            r['solved'] = {'solving': solving}
        n_skip = len(rows) - n_total
        LOG.info('skip = %d, total = %d (%.2f)' % (n_skip, n_total, n_total * 100. / len(rows)))

        standings = {
            'result': result,
            'url': self.STANDING_URL_.format(self),
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://csacademy.com/contest/round-49/', key='26759')
    pprint(statistic.get_standings(['aropan']))
