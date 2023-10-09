#!/usr/bin/env python

import html
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from pprint import pprint
from urllib.parse import urljoin

from first import first
from multiset import Multiset

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if '//stats.ioinformatics.org/olympiads/' not in self.url:
            raise InitModuleException(f'Url {self.url} should be contains stats.ioinformatics.org/olympiads')

    def get_standings(self, users=None, statistics=None):
        result = {}
        hidden_fields = OrderedDict()
        problems_info = OrderedDict()
        year = self.start_time.year
        row_index = 0
        duration_in_secs = None

        def set_member(v, row):
            nonlocal row_index
            if not v.value:
                row_index += 1
                member = f'{year}-{row_index:06d}'
                row['member'] = member
                info = row.setdefault('info', {})
                info['is_virtual'] = True
            else:
                url = first(v.column.node.xpath('a[@href]/@href'))
                member = url.strip('/').split('/')[-1]
                row['member'] = member
                row['name'] = v.value
                if statistics and member in statistics:
                    row['problems'] = statistics[member].get('problems', {})

        if not self.standings_url:
            self.standings_url = self.url.replace('/olympiads/', '/results/')

        url = self.url.replace('/olympiads/', '/tasks/')
        page = REQ.get(url)
        regex = '<table[^>]*>.*?</table>'
        found = re.search(regex, page, re.DOTALL)
        if found:
            table = parsed_table.ParsedTable(found.group(0))
            short_names = []
            for r in table:
                href = first(r['Name'].column.node.xpath('.//a/@href'))
                url = urljoin(self.standings_url, '/' + href.lstrip('/'))
                short = url.rstrip('/').rsplit('/', 1)[-1]

                short_names.append(short)
                d = problems_info.setdefault(short, {
                    'short': short,
                    'name': html.unescape(r['Name'].value),
                    'url': url,
                })

                full_score = as_number(r['Max. Score'].value, force=True)
                if full_score is not None:
                    d['full_score'] = full_score

        page = REQ.get(self.standings_url)
        regex = '<table[^>]*>.*?</table>'
        found = re.search(regex, page, re.DOTALL)
        if found:
            table = parsed_table.ParsedTable(found.group(0), as_list=True)
        else:
            table = []
        has_standings_table = bool(found)
        custom_start_time = 0

        for r in table:
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            for k, v in r:
                if 'taskscore' in v.header.attrs.get('class', '').split():
                    url = v.header.node.xpath('.//a/@href')[0]
                    assert 'tasks/' in url
                    short = url.rstrip('/').rsplit('/', 1)[-1]
                    d = problems_info[short]
                    score = as_number(v.value, force=True)
                    if score:
                        p = problems.setdefault(short, {})
                        p['result'] = score
                        p['partial'] = score < d['full_score']
                elif k == 'Abs.':
                    row['solving'] = float(v.value)
                elif k == 'Rank':
                    row['place'] = v.value.strip('*').strip('.')
                elif k == 'Contestant':
                    set_member(v, row)
                elif k == 'Country':
                    country = re.sub(r'\s*[0-9]+$', '', v.value)
                    if country:
                        row['country'] = country
                else:
                    val = v.value.strip()
                    if k in ('Medal', 'Award'):
                        k = 'medal'
                        val = val.lower()
                        if val == 'honourable mention':
                            val = 'honorable'
                    if val:
                        row[k.lower()] = val
            for k in row.keys():
                hidden_fields[k] = False
            result[row['member']] = row

        url = self.url.replace('/olympiads/', '/contestants/')
        page = REQ.get(url)
        regex = '<table[^>]*>.*?</table>'
        found = re.search(regex, page, re.DOTALL)
        if found:
            table = parsed_table.ParsedTable(found.group(0))
            for idx, r in enumerate(table):
                contestant = r.pop('Contestant', None)
                if contestant is None:
                    continue
                row = OrderedDict()
                set_member(contestant, row)
                row = result.setdefault(row['member'], row)

                for k, v in r.items():
                    k = k.strip('▲').strip()
                    if re.search('[a-z]', k):
                        k = k.replace(' ', '_').lower()
                    else:
                        k = k.replace(' ', '')
                    hidden_fields.setdefault(k, k not in ['country'])

                    href = first(v.column.node.xpath('.//a[contains(@class, "tableimglink")]/@href'))
                    if href:
                        value = href.strip('/').rsplit('/', 2)[-1]
                        row[k] = value
                    elif k == 'country':
                        row[k] = re.sub(r'\s*[0-9]+$', '', v.value)
                    elif k not in row and v.value:
                        row[k] = v.value

        def get_ranking_url(path):
            nonlocal ranking_url
            if not ranking_url:
                return None
            try:
                response = REQ.get(urljoin(ranking_url, path), return_json=True, force_json=True, ignore_codes={404})
            except json.decoder.JSONDecodeError:
                return None
            if isinstance(response, dict) and response.get('__no_json'):
                return None
            return response

        ranking_url = self.info.get('_official_website_ranking')
        if not ranking_url:
            page = REQ.get(self.url)
            sample = re.search(r'<a[^>]*href="(?P<href>[^"]*)"[^>]*>\s*official\s*website<\s*/a>', page, re.I)
            if sample:
                ranking_url = sample.group('href').replace('//', '//ranking.')

        if ranking_url:
            ranking_url = REQ.geturl(ranking_url)
            users = get_ranking_url('users/')
        else:
            users = None

        if users:

            def get_alpha_substring_multiset(value):
                ret = Multiset()
                value = value.lower()
                for i in range(len(value)):
                    w = ''
                    for c in value[i:]:
                        if not c.isalpha():
                            break
                        w += c
                        ret.add(w)
                return ret

            def multiset_hash(multiset):
                ret = tuple()
                for k, v in sorted(multiset.items()):
                    ret += (k, v)
                return hash(ret)

            user_mapping = dict()
            rows = {k: v['name'] for k, v in result.items() if 'name' in v}
            rows_sets = dict()
            for member, name in rows.items():
                name_set = get_alpha_substring_multiset(name)
                name_set_hash = multiset_hash(name_set)
                assert name_set_hash not in rows_sets
                rows_sets[name_set_hash] = member

            def add_mapping(user, member):
                user_mapping[user] = member

                name_set = get_alpha_substring_multiset(rows[member])
                name_set_hash = multiset_hash(name_set)
                rows_sets.pop(name_set_hash)

                users.pop(user)
                rows.pop(member)

            while users:
                mapping = []
                max_iou = -1
                for user, info in list(users.items()):
                    info_name = info['f_name'] + ' ' + info['l_name']
                    info_set = get_alpha_substring_multiset(info_name)
                    info_set_hash = multiset_hash(info_set)
                    if info_set_hash in rows_sets:
                        add_mapping(user, rows_sets[info_set_hash])
                        continue

                    for member, name in rows.items():
                        name_set = get_alpha_substring_multiset(name)
                        intersection = len(name_set & info_set)
                        union = len(name_set) + len(info_set) - intersection
                        iou = intersection / union
                        if iou > max_iou:
                            mapping = []
                            max_iou = iou
                        if iou == max_iou:
                            mapping.append((user, member, name, info_name))
                user, member, *_ = mapping[0]
                add_mapping(user, member)

            contests = get_ranking_url('contests/')
            duration_in_secs = 0
            for contest in contests.values():
                contest['time_shift'] = duration_in_secs
                duration_in_secs += contest['end'] - contest['begin']

            tasks = get_ranking_url('tasks/')
            if isinstance(tasks, dict):
                tasks = list(tasks.values())
            tasks.sort(key=lambda t: (t['contest'], t['order']))
            tasks = {t['short_name']: t for t in tasks}
            if not has_standings_table:
                for task in tasks.values():
                    problems_info[task['short_name']] = {
                        'name': task['name'],
                        'short': task['short_name'],
                        'full_score': task['max_score'],
                    }
            for task in tasks.values():
                if 'extra_headers' in task:
                    problems_info[task['short_name']]['subtasks'] = task.pop('extra_headers')

            history = get_ranking_url('history')
            history.sort(key=lambda x: x[2])
            for user, short, timestamp, score in history:
                member = user_mapping[user]
                row = result[member]
                task = tasks[short]

                problems = row.setdefault('problems', {})
                problem = problems.setdefault(short, {})

                if score > as_number(problem.get('result', -1)):
                    problem.pop('time', None)
                    problem['result'] = score

                problem['partial'] = problem['result'] < problems_info[short]['full_score']
                contest = contests[task['contest']]
                custom_start_time = max(custom_start_time, contest['end'] - duration_in_secs)
                time_in_seconds = timestamp - contest['begin']
                if problem['result'] == score and 'time' not in problem:
                    problem['time_in_seconds'] = time_in_seconds
                    problem['time'] = self.to_time(time_in_seconds, num=3)
                    problem['absolute_time'] = self.to_time(contest['time_shift'] + time_in_seconds, num=3)
                if problem.get('_attempt_time', -1) < time_in_seconds:
                    problem.setdefault('attempt', 0)
                    problem['attempt'] += 1
                    problem['_attempt_time'] = time_in_seconds

            if not has_standings_table:
                scores = get_ranking_url('scores')
                for user, score in scores.items():
                    member = user_mapping[user]
                    solving = sum(score.values())
                    result[member]['solving'] = solving
                for row in result.values():
                    row.setdefault('solving', 0)

                place = None
                last = None
                sorted_result = sorted(result.values(), key=lambda row: row['solving'], reverse=True)
                for idx, row in enumerate(sorted_result, start=1):
                    if last != row['solving']:
                        last = row['solving']
                        place = idx
                    row['place'] = place

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': [k for k, v in hidden_fields.items() if v],
            'custom_start_time': custom_start_time if custom_start_time else None,
            'series': 'ioi',
        }

        if duration_in_secs is not None:
            standings['duration_in_secs'] = duration_in_secs

        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_ratings(user, account):
            if account.info.get('is_virtual'):
                return user, False

            url = resource.profile_url.format(**account.dict_with_info())
            page = REQ.get(url)

            info = {}
            samples = re.finditer('<div[^>]*class="(?P<key>[^"]*)"[^>]*>(?P<value>[^<]*)</div>', page)
            for sample in samples:
                key = sample.group('key').lower()
                if key in ['sorttriangle', 'mainheader']:
                    continue
                value = html.unescape(sample.group('value'))
                info[key] = value

            sample = re.search('<img[^>]*class="[^"]*participantflag[^"]*"[^>]*src="(?P<src>[^"]*)"[^>]*>', page)
            if sample:
                info['avatar_url'] = urljoin(url, '/' + sample.group('src').lstrip('/'))

            samples = re.finditer(r'<a[^>]*href="(?P<href>[^>]*)"[^>]*>\s*<img[^>]*src="[^"]*/contacts/[^"]*"[^>]*alt="(?P<name>[^"]*)"[^>]*>', page)  # noqa
            for sample in samples:
                key = sample.group('name').lower()
                info.setdefault('contacts', {})[key] = sample.group('href')

            return user, info

        with PoolExecutor(max_workers=8) as executor:
            for user, info in executor.map(fetch_ratings, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue
                info = {'info': info}
                yield info


if __name__ == "__main__":
    statictic = Statistic(url='http://stats.ioinformatics.org/olympiads/2008', standings_url=None)
    pprint(statictic.get_result('804'))
