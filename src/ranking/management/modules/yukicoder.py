# -*- coding: utf-8 -*-

import collections
import html
import re
from urllib.parse import urljoin

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        problem_url = self.url
        try:
            page = REQ.get(problem_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e
        match = re.search('<table[^>]*class="table"[^>]*>.*?</table>', page, re.MULTILINE | re.DOTALL)
        if not match:
            raise ExceptionParseStandings('Not found problems table')
        header_mapping = {
            '#': 'short',
            'ナンバー': 'code',
            '問題名': 'name',
            'レベル': 'level',
            '作問者': 'writer',
            'テスター': 'tester',
            'Solved': 'n_solved',
            'Fav': 'n_fav',
            '順位': 'place',
            'ユーザー名': 'name',
            'Total': 'total',
        }
        table = parsed_table.ParsedTable(match.group(0), header_mapping=header_mapping)

        problems_info = collections.OrderedDict()

        writers = collections.defaultdict(int)
        for row in table:
            info = {}
            for k, v in row.items():
                if k == 'level':
                    stars = v.column.node.xpath('.//*[contains(@class, "fa-star")]')
                    level = 0
                    for star in stars:
                        classes = star.get('class').split()
                        if 'fa-star-half' in classes:
                            level += 0.5
                        elif 'fa-star' in classes:
                            level += 1.0
                    info[k] = level
                elif k == 'writer':
                    a = v.column.node.xpath('.//a')
                    if a:
                        writer = a[0].get('href').strip('/').split('/')[-1]
                        info['writer'] = writer
                else:
                    info[k] = v.value
            info['url'] = urljoin(problem_url, f'/problems/no/{info["code"]}')
            problems_info[info['short']] = info

            if info.get('writer'):
                writers[info['writer']] += 1

        standings_url = self.standings_url or self.url.rstrip('/') + '/table'
        page = REQ.get(standings_url)
        match = re.search('<table[^>]*class="table"[^>]*>.*?</table>', page, re.MULTILINE | re.DOTALL)
        if not match:
            raise ExceptionParseStandings('Not found standings table')

        def get_stat(value):
            a = value.split()
            res = a.pop(0)
            ret = {'result': int(res) if res.isdigit() else float(res)}

            m = re.match(r'^\(([0-9]+)\)$', a[0])
            if m:
                ret['penalty'] = int(m.group(1))
                a.pop(0)

            n_days = None
            m = re.match('^([0-9]+)d$', a[0])
            if m:
                n_days = m.group(1)
                a.pop(0)
            m = re.match('^[0-9:]+$', a[0])
            if m:
                if n_days:
                    ret['time'] = n_days + ':' + a[0] + ':00' * (2 - a[0].count(':'))
                else:
                    ret['time'] = a[0]
                a.pop(0)

            if a and a[0].lower() in ['writer', 'tester']:
                ret['partial'] = False
            if a:
                ret['status'] = a[-1]

            return ret

        table = parsed_table.ParsedTable(match.group(0), header_mapping=header_mapping)
        place = 0
        rank = 0
        last_res = None
        result = {}
        for row in table:
            r = {'solved': {'solving': 0}}
            problems = r.setdefault('problems', {})
            for k, v in row.items():
                match = re.search('^(?P<short>[A-Z]) No.(?P<code>[0-9]+)', k)
                if match:
                    a = v.value.split()
                    if len(a) < 1 or a[1] == '-' or len(a) == 2 and a[0] == '0':
                        continue
                    p = problems.setdefault(match.group('short'), {})
                    stat = get_stat(v.value)
                    stat.pop('status', None)
                    p.update(stat)
                    if 'partial' in p and not p['partial']:
                        info = problems_info[match.group('short')]
                        if 'full_score' in info:
                            info['full_score'] = max(p['result'], info['full_score'])
                        else:
                            info['full_score'] = p['result']
                    if p['result'] > 1e-9:
                        r['solved']['solving'] += 1
                    elif 'penalty' in p:
                        p['result'] = -p.pop('penalty')
                    a = v.column.node.xpath('.//a[contains(@href, "submissions")]')
                    if a:
                        p['url'] = urljoin(standings_url, a[0].get('href'))
                        p['external_solution'] = True
                elif k == 'total':
                    stat = get_stat(v.value)
                    r['solving'] = stat['result']
                    r['penalty'] = stat['time']
                    if stat.get('status'):
                        r['status'] = stat['status']
                elif k == 'name':
                    img = v.column.node.xpath('.//a/img')
                    if img:
                        src = img[0].get('src')
                        if src:
                            r['info'] = {'avatar_url': urljoin(standings_url, src)}
                    name = v.column.node.xpath('.//a/text()')
                    if name and name[0]:
                        r['name'] = name[0]
                    a = v.column.node.xpath('.//a')
                    if a:
                        member = a[0].get('href').strip('/').split('/')[-1]
                        r['member'] = member
                else:
                    r[k] = v.value
            if not problems:
                continue
            if 'status' in r:
                r.pop('place', None)
                r['_no_update_n_contests'] = True
            else:
                curr_res = (r['solving'], r['penalty'])
                rank += 1
                if curr_res != last_res:
                    last_res = curr_res
                    place = rank
                r['place'] = place
            result[r['member']] = r

        for r in result.values():
            if 'place' not in r:
                continue
            for k, p in r['problems'].items():
                info = problems_info[k]
                if 'full_score' in info and p['result'] > info['full_score'] - 1e-9:
                    p['first_ac'] = True
                if p['result'] > 1e-9:

                    def time_to_tuple(s):
                        a = list(map(int, s.split(':')))
                        return (len(a), a)

                    if 'first_ac_time' not in info or time_to_tuple(p['time']) < time_to_tuple(info['first_ac_time']):
                        info['first_ac_time'] = p['time']

        standings = {
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': ['status'],
        }

        if writers:
            writers = [w[0] for w in sorted(writers.items(), key=lambda w: w[1], reverse=True)]
            standings['writers'] = writers

        return standings

    @staticmethod
    def get_source_code(contest, problem):
        page = REQ.get(problem['url'])
        match = re.search('<pre[^>]*id="code"[^>]*>(?P<solution>.*?)</pre>', page, re.DOTALL)
        if not match:
            return {}
        solution = html.unescape(match.group('solution'))
        ret = {'solution': solution}
        match = re.search('data-ace-mode="(?P<lang>[^"]*)"', page)
        if match:
            ret['language'] = match.group('lang')
        return ret
