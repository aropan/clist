#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import json
from collections import OrderedDict

from ranking.management.modules.common import REQ, DOT, BaseModule, parsed_table


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        page = REQ.get(self.url)
        match = re.search(r'''<a[^>]*href=["']?(?P<href>[^"' ]*rating[^"' ]*)["']?[^>]*>\[Рейтинг\]''', page)

        if not match and re.search(r'''<b>Олимпиада №[0-9]+ не существует!</b>''', page):
            return {'action': 'delete'}

        page = REQ.get(match.group('href'))
        standings_url = REQ.last_url

        match = re.search(r'''var(?P<vars>(?:\s*[a-z]+=[0-9]+,)+)\s*M=(?:new Array)?[\[\(]?(?P<data>.*?)[\]\)]\s*(?:function|var)''', page)  # noqa

        result = {}
        problems_info = OrderedDict()

        def canonize_name(name):
            name = name.replace('\r', ' ')
            name = name.replace('\n', ' ')
            name = re.sub(r'\s+', ' ', name)
            name = re.sub(r'<br/?>', ',', name)
            name = re.sub(r'<[^>]*>', '', name)
            name = re.sub(r'\s*,\s*', ', ', name)
            name = name.strip()
            return name

        if match:
            data = match.group('data')
            data = data.replace('\\', '\\\\')
            data = data.replace('"', r'\"')
            data = data.replace("'", '"')
            data = re.sub(r'\s+', ' ', data)
            data = json.loads(f'[{data}]')

            variables = {}
            for var in re.split(r',\s*', match.group('vars').strip()):
                if not var:
                    continue
                k, v = var.split('=')
                variables[k] = v

            match = re.search(r'''M\[\((?P<val>[0-9]+)\+''', page)
            offset = int(match.group('val'))

            n_problems = int(variables['tn'])
            n_teams = int(variables['nk'])
            n_fields = offset + 3 * n_problems
            place = 0
            last = None
            for rank, st in enumerate(range(0, n_teams * n_fields, n_fields), start=1):
                row = data[st:st + n_fields]

                name = canonize_name(row[0])

                member = name + ', ' + season

                r = result.setdefault(member, {})

                r['name'] = name
                r['member'] = member
                r['solving'] = int(row[1])
                r['penalty'] = int(row[2])

                score = r['solving'], r['penalty']
                if score != last:
                    place = rank
                    last = score
                r['place'] = place

                n_problems_fields = 3
                problems = r.setdefault('problems', {})
                for idx in range(0, n_problems):
                    p_info = row[offset + idx * n_problems_fields:offset + (idx + 1) * n_problems_fields]
                    stat, errors, seconds = map(int, p_info)
                    key = chr(ord('A') + idx) if n_problems < 27 else f'{idx + 1:02d}'

                    if key not in problems_info:
                        info = {'short': key}
                        if abs(errors) >= 1000:
                            info['full_score'] = 100
                        problems_info[key] = info

                    if not stat:
                        continue
                    p = problems.setdefault(key, {})
                    p['time'] = self.to_time(seconds, num=2)
                    if abs(errors) < 1000:
                        p['result'] = f'+{errors if errors else ""}' if stat == 1 else f'-{errors}'
                    else:
                        solved = r.setdefault('solved', {'solving': 0})
                        score = errors - 1000
                        p['result'] = score
                        if score > 0:
                            p['partial'] = score < problems_info[key]['full_score']
                            if not p['partial']:
                                solved['solving'] += 1

                if not problems:
                    result.pop(member)
        else:
            regex = '''<table[^>]*class=["']?olimp["']?[^>]*>.*?</table>'''
            match = re.search(regex, page, re.DOTALL)
            if not match and 'Рейтинг олимпиады' not in page:
                return {'action': 'delete'}
            table = parsed_table.ParsedTable(match.group(0))

            for row in table:
                r = OrderedDict()
                problems = r.setdefault('problems', {})
                for k, v in list(row.items()):
                    if k == '=':
                        r['solving'] = int(v.value)
                    elif k == 'Место':
                        r['place'] = int(v.value)
                    elif k == 'Время':
                        r['penalty'] = int(v.value)
                    elif k == 'Участник':
                        name = canonize_name(v.value)
                        r['name'] = name
                        r['member'] = name + ', ' + season
                    elif len(k) == 1 and k not in ['№']:
                        if k not in problems_info:
                            info = {'short': k}
                            problems_info[k] = info
                        if v.value != DOT:
                            p = problems.setdefault(k, {})
                            p['result'], *values = v.value.split()
                            if values:
                                p['time'] = values[0]
                if not problems:
                    continue

                result[r['member']] = r

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        }
        return standings
