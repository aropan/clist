#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
from pprint import pprint
from functools import partial
from collections import OrderedDict

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.url = self.key

    @staticmethod
    def get_value_by_keys_(fields, *keys):
        for k in keys:
            if k in fields:
                return fields[k]
        raise ExceptionParseStandings('No found %s key in %s' % (keys, fields))

    def get_standings(self, users=None, statistics=None, **kwargs):
        result = {}
        standings_url = None
        problems_info = OrderedDict()
        for url, upsolve in (
            (self.url, False),
            (self.url.replace(".html", "-upsolving.html"), True),
            (self.url.replace("-training-", "-practice-"), True),
            (self.key, False),
            (self.key.replace(".html", "-upsolving.html"), True),
            (self.key.replace("-training-", "-practice-"), True),
        ):
            if upsolve and url in [self.url, self.key]:
                continue
            try:
                page = REQ.get(url)
            except Exception:
                continue
            if standings_url is None:
                standings_url = url

            header = None
            for match in re.findall(r'<tr[^>]*>.*?<\/tr>', page):
                match = match.replace('&nbsp;', ' ')
                fields = [re.sub('<[^>]*>', ' ', m).strip() for m in re.findall(r'<t[hd][^>]*>.*?\/t[hd]>', match)]

                if re.search(r'<\/th>', match):
                    header = fields
                    continue

                if not header:
                    continue

                fields = dict(list(zip(header, fields)))
                get_value = partial(self.get_value_by_keys_, fields)

                place = get_value('Место', 'Place')
                if not place:
                    continue
                member = get_value('Логин', 'Login', 'User', 'Участник')
                row = result.setdefault(member, {'member': member})

                type_ = ('up' if upsolve else '') + 'solving'
                row[type_] = int(get_value('Всего', 'Решённые задачи', 'Total', 'Score'))

                problems = row.setdefault('problems', {})
                for k in sorted(fields.keys()):
                    if re.match('^(?:[A-Z]|[0-9]{,2})$', k):
                        problems_info[k] = {'short': k}
                        v = fields[k].split()
                        if len(v) > 0:
                            p = {'result': v[0]}
                            if len(v) > 1:
                                p['time'] = re.sub('[^0-9:]', '', v[1])
                            if upsolve:
                                a = problems.setdefault(k, {})
                                if a.get('result', None) != p['result']:
                                    a['upsolving'] = p
                            else:
                                problems[k] = p

                try:
                    solved = int(get_value('Решённые задачи', 'Solved problems'))
                    row.setdefault('solved', {})[type_] = solved
                except ExceptionParseStandings:
                    pass

                if upsolve:
                    row['upsolving'] -= row.get('solving', 0)
                    if 'solved' in row:
                        row['solved']['upsolving'] -= row['solved'].get('solving', 0)
                else:
                    row['place'] = place

            if not header:
                raise ExceptionParseStandings('Not detect header')

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }
        if standings_url is not None:
            standings['url'] = standings_url
        return standings


