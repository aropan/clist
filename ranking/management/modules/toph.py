#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from pprint import pprint

import tqdm
import yaml

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        try:
            page = REQ.get(self.url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete', 'force': True}
            raise e

        try:
            page = REQ.get(f'/problems/contests/{self.key}')
        except FailOnGetResponse as e:
            if e.code == 404:
                raise ExceptionParseStandings('not found problems')
            raise e

        table = parsed_table.ParsedTable(html=page, without_header=True, ignore_wrong_header_number=False)
        contest_problems = []
        with_letter = True
        writers = collections.defaultdict(int)
        for r in table:
            r = r.columns[0]
            problem = {}

            name = r.node.xpath('.//a/text()')
            if not name:
                name = r.node.xpath('.//div/text()')
            name = name[0]
            name = re.sub(r'\s+', ' ', name).strip()
            problem['name'] = name
            if not re.match(r'^[A-Z][0-9]*\.', name):
                with_letter = False

            href = r.node.xpath('.//a[starts-with(@href,"/p/")]/@href')
            if href:
                url = urllib.parse.urljoin(REQ.last_url, href[0])
                problem['url'] = url
                problem['code'] = url.strip('/').split('/')[-1]

            problem['writers'] = r.node.xpath('.//a[contains(@class,"handle")]/text()')
            for writer in problem['writers']:
                writers[writer] += 1

            tags = problem.setdefault('tags', [])
            for tag in r.node.xpath('.//a[contains(@href,"/tags/")]/text()'):
                tag = re.sub('([^A-Z])([A-Z])', r'\1-\2', tag).lower()
                tags.append(tag)
            contest_problems.append(problem)
        if with_letter:
            for problem in contest_problems:
                short, name = [s.strip() for s in problem['name'].split('.', 1)]
                problem['name'] = name
                problem['short'] = short

        writers = [w for w, _ in sorted(writers.items(), key=lambda r: -r[1])]

        standings_url = self.url.strip('/') + '/standings'
        next_url = standings_url

        urls = []
        results = {}
        problems_info = collections.OrderedDict()
        n_page = 1
        has_penalty = False
        rank = 0
        while next_url:
            page = REQ.get(next_url)
            table = parsed_table.ParsedTable(html=page)
            for r in table:
                to_get_handle = False
                row = {}
                problems = row.setdefault('problems', {})
                pind = 0
                rank += 1
                for k, v in r.items():
                    if k == '#':
                        row['place'] = v.value
                    elif not k:
                        name, *infos, score = v

                        texts = name.column.node.xpath('.//a[contains(@class,"handle")]/text()')
                        row['name'] = texts[0] if texts else name.value
                        hrefs = name.column.node.xpath('.//a[contains(@href,"/u/")]/@href')
                        if hrefs:
                            row['member'] = [h.rstrip('/').split('/')[-1] for h in hrefs]
                            row['info'] = {'is_virtual': False}
                            if len(row['member']) > 1:
                                row['name'] = re.sub(r'\s+,', ',', name.value)
                                row['team_id'] = f'{self.pk}_{rank}'
                                row['_members'] = [{'account': m} for m in row['member']]
                        else:
                            to_get_handle = True
                            row['member'] = f'{row["name"]}, {row["place"]}, {self.start_time.year}'
                            row['info'] = {'is_virtual': True}

                        for field in v:
                            flag = field.row.node.xpath(".//span[contains(@class,'flag')]/@class")
                            if flag:
                                for f in flag[0].split():
                                    if f == 'flag-icon':
                                        continue
                                    for p in 'flag-icon-', 'flag-':
                                        if f.startswith(p):
                                            row['country'] = f[len(p):]
                                            break

                        title = score.column.node.xpath('.//div[@title]/@title')[0]
                        row['solving'], penalty = title.replace(',', '').split()
                        if penalty.isdigit():
                            penalty = int(penalty)
                        row['penalty'] = penalty
                        has_penalty |= bool(penalty)

                        for field in v:
                            if 'rating' in field.attrs.get('class', '').split():
                                cs = field.column.node.xpath('.//*/@class')
                                if cs:
                                    cs = cs[0].split()
                                    if 'fa-angle-double-up' in cs or 'font-green' in cs:
                                        row['rating_change'] = int(field.value)
                                        break
                                    if 'fa-angle-double-down' in cs or 'text-muted' in cs:
                                        row['rating_change'] = -int(field.value)
                                        break
                            trending = field.column.node.xpath('.//img[contains(@src,"/trending-")]/@src')
                            if trending:
                                value = field.value.split()[-1]
                                if '-up-' in trending[0]:
                                    row['rating_change'] = int(value)
                                elif '-down-' in trending[0]:
                                    row['rating_change'] = -int(value)
                                else:
                                    raise ExceptionParseStandings(f'Unknown trending = {trending[0]}')
                                break

                    else:
                        letter = k.rsplit(' ', 1)[0].strip()
                        if letter not in problems_info:
                            problems_info[letter] = {'short': letter}
                        if (
                            len(letter) == 1
                            or re.match('^[A-Z][0-9]+$', letter)
                            or pind < len(contest_problems) and (contest_problems[pind].get('name') == letter or
                                                                 contest_problems[pind].get('short') == letter)
                        ):
                            if v.value:
                                title = v.column.node.xpath('.//div[@title]/@title')[0]
                                if ',' in title:
                                    variables = yaml.safe_load(re.sub(r',\s*', '\n', title.lower()))
                                    time = int(variables['minutes'])
                                    attempt = int(variables['rejections']) + 1
                                else:
                                    _, time, attempt = title.split()
                                    time = int(time)
                                    attempt = sum(map(int, re.findall('[0-9]+', attempt)))

                                p = problems.setdefault(letter, {})

                                divs = v.column.node.xpath('.//a[contains(@href,"submissions")]/div/text()')
                                if len(divs) == 2 and divs[0]:
                                    result = divs[0].strip()
                                    cs = v.column.node.xpath('.//a[contains(@href,"submissions")]/div/@class')
                                    if result != '0' and cs:
                                        cs = cs[0].split()
                                        if 'font-orange' in cs:
                                            p['partial'] = True
                                    p['attempts'] = attempt
                                    if isinstance(row.get('penalty'), int):
                                        penalty = row['penalty']
                                        row['penalty'] = f'{penalty // 60:02}:{penalty % 60:02}'
                                elif not v.column.node.xpath('.//img[@src]'):
                                    score, *_ = v.value.split()
                                    result = int(score)
                                    p['partial'] = not bool(v.column.node.xpath('.//*[contains(@class,"font-green")]'))
                                    solved = row.setdefault('solved', {'solving': 0})
                                    if not p['partial']:
                                        solved['solving'] += 1
                                    if attempt > 1:
                                        p['penalty'] = attempt - 1
                                elif time:
                                    result = '+' if attempt == 1 else f'+{attempt - 1}'
                                else:
                                    result = f'-{attempt}'
                                if time:
                                    time = f'{time // 60:02}:{time % 60:02}'
                                    p['time'] = time
                                p['result'] = result

                                hrefs = v.column.node.xpath('.//a[contains(@href,"submissions")]/@href')
                                if hrefs:
                                    url = urllib.parse.urljoin(next_url, hrefs[0])
                                    p['url'] = url
                                    if to_get_handle:
                                        urls.append((row['member'], url))
                                        to_get_handle = False

                                if (
                                    v.column.node.xpath('.//a/div/*[contains(@class,"fa fa-star")]')
                                    or v.column.node.xpath('.//a/div/img[contains(@src,"checkmark-done-sharp")]')
                                    or v.column.node.xpath('.//a/div/img[contains(@src,"/star.svg")]')
                                ):
                                    p['first_ac'] = True
                        pind += 1
                if not problems:
                    continue

                if isinstance(row['member'], list):
                    rows = []
                    members = row['member']
                    for member in members:
                        r = deepcopy(row)
                        r['member'] = member
                        rows.append(r)

                else:
                    rows = [row]

                for row in rows:
                    handle = row['member']
                    if users and handle not in users:
                        continue

                    stats = statistics.get(handle, {})
                    for f in 'old_rating', 'rating_change', 'new_rating':
                        if f in stats and f not in row:
                            row[f] = stats[f]

                    results[handle] = row
            n_page += 1
            match = re.search(rf'<a[^>]*href="(?P<href>[^"]*standings[^"]*|\?[^"]*)"[^>]*>{n_page}</a>', page)
            next_url = urllib.parse.urljoin(next_url, match.group('href')) if match else None

        if not has_penalty:
            for r in results.values():
                r.pop('penalty', None)

        if urls:
            def fetch(info):
                member, url = info
                return member, REQ.get(url)
            with PoolExecutor(max_workers=20) as executor, tqdm.tqdm(total=len(urls), desc='handling') as pbar:
                for member, page in executor.map(fetch, urls):
                    t = parsed_table.ParsedTable(html=page)
                    t = next(iter(t))
                    handle = t['Author'].value
                    results[handle] = results.pop(member)
                    results[handle]['member'] = handle
                    pbar.update()

        problems = []
        for info, contest_info in zip(problems_info.values(), contest_problems):
            info.update(contest_info)
            problems.append(info)

        ret = {
            'url': standings_url,
            'problems': problems,
            'result': results,
            'writers': writers,
        }

        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def fetch_ratings(user, account):
            if account.info.get('is_virtual'):
                return user, False, None
            try:
                page = REQ.get(f'https://toph.co/u/{user}/ratings')
            except FailOnGetResponse as e:
                if e.code == 404:
                    return user, None, None
                return user, False, None

            tables = re.findall('<table[^>]*>.*?</table>', page, re.DOTALL)
            t = parsed_table.ParsedTable(html=tables[-1])
            ratings = {}
            info = {}
            for row in t:
                href = row['Contest'].column.node.xpath('.//a/@href')[0]
                key = href.rstrip('/').split('/')[-1]
                rating = int(row['Rating'].value)
                ratings[key] = {'new_rating': rating}
                info.setdefault('rating', rating)

            matches = re.finditer('''
                 <div[^>]*class="?value"?[^>]*>(?P<value>[^<]*)</div>[^<]*
                 <div[^>]*class="?title"?>(?P<key>[^<]*)</div>
            ''', page, re.DOTALL | re.VERBOSE)
            for match in matches:
                key = match.group('key').lower()
                value = match.group('value')
                info[key] = value
            return user, info, ratings

        with PoolExecutor(max_workers=8) as executor:
            for user, info, ratings in executor.map(fetch_ratings, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True, 'delta': timedelta(days=365)}
                    continue
                info = {
                    'info': info,
                    'contest_addition_update_params': {
                        'update': ratings,
                        'by': 'key',
                    },
                }
                yield info


if __name__ == "__main__":
    statictic = Statistic(
        name='Criterion 2020 Round 1 Standings',
        url='https://toph.co/c/criterion-2020-round-1',
        key='criterion-2020-round-1',
        start_time=datetime.strptime('20.09.2019', '%d.%m.%Y'),
    )
    pprint(statictic.get_standings(['EgorKulikov']))
    statictic = Statistic(
        name='DIU Intra University Programming Contest 2019 (Replay)',
        url='https://toph.co/c/diu-inter-section-summer-2019-preliminary-a',
        key='diu-inter-section-summer-2019-preliminary-a',
        start_time=datetime.strptime('20.09.2019', '%d.%m.%Y'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        name='DIU Intra University Programming Contest 2019 (Replay)',
        url='https://toph.co/c/diu-intra-2019-r',
        key='diu-intra-2019-r',
        start_time=datetime.strptime('20.09.2019', '%d.%m.%Y'),
    )
    pprint(statictic.get_standings(['salman.exe']))
