#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
from pprint import pprint
from datetime import datetime
import urllib.parse
import re
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
import tqdm

from ranking.management.modules.common import REQ, BaseModule, parsed_table


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        page = REQ.get(self.url)

        page = REQ.get(self.url.strip('/') + '/statistics')
        table = parsed_table.ParsedTable(html=page)
        problem_names = [list(r.values())[0].value for r in table]

        standings_url = self.url.strip('/') + '/standings'
        next_url = standings_url

        urls = []
        results = {}
        problems_info = collections.OrderedDict()
        n_page = 1
        while next_url:
            page = REQ.get(next_url)
            table = parsed_table.ParsedTable(html=page)
            for r in table:
                to_get_handle = False
                row = {}
                problems = row.setdefault('problems', {})
                for k, v in r.items():
                    if k == '#':
                        row['place'] = v.value
                    elif not k:
                        name, *infos, score = v

                        row['name'] = name.value
                        hrefs = name.column.node.xpath('.//a[contains(@href,"/u/")]/@href')
                        if hrefs:
                            row['member'] = hrefs[0].split('/')[-1]
                        else:
                            to_get_handle = True
                            row['member'] = f'{row["name"]}, {row["place"]}, {self.start_time.year}'
                        flag = score.row.node.xpath(".//span[contains(@class, 'flag')]/@class")
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

                        for info in infos:
                            if 'rating' in info.attrs['class'].split():
                                cs = info.row.node.xpath('.//i/@class')
                                if cs:
                                    cs = cs[0].split()
                                    if 'fa-angle-double-up' in cs:
                                        row['rating_change'] = int(info.value)
                                    if 'fa-angle-double-down' in cs:
                                        row['rating_change'] = -int(info.value)
                    else:
                        letter = k.split()[0]
                        problems_info[letter] = {'short': letter}
                        if len(letter) == 1:
                            if v.value:
                                title = v.column.node.xpath('.//div[@title]/@title')[0]
                                *_, time, attempt = title.split()
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
                                if v.column.node.xpath('.//a/div/*[contains(@class,"fa fa-star")]'):
                                    p['first_ac'] = True
                if not problems:
                    continue
                if users and row['member'] not in users:
                    continue

                results[row['member']] = row
            n_page += 1
            match = re.search(f'<a[^>]*href="(?P<href>[^"]*standings[^"]*)"[^>]*>{n_page}</a>', page)
            next_url = urllib.parse.urljoin(next_url, match.group('href')) if match else None

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
        for info, name in zip(problems_info.values(), problem_names):
            info['name'] = name
            problems.append(info)

        ret = {
            'url': standings_url,
            'problems': problems,
            'result': results,
        }
        return ret


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
