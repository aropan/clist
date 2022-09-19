#!/usr/bin/env python

import html
import re
import urllib.parse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from pprint import pprint
from time import sleep

import tqdm
from first import first
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = f'{self.url.rstrip("/")}/leaderboard'

    def get_standings(self, users=None, statistics=None):

        result = {}
        problems_info = OrderedDict()

        try:
            page = REQ.get(self.standings_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                return {'action': 'delete'}
            raise e
        match = re.findall('<a[^>]href="[^"]*page=[0-9]+"[^>]*>(?P<n_page>[0-9]+)</a>', page)
        n_page = 1 if not match else int(match[-1])

        @RateLimiter(max_calls=1, period=1)
        def fetch_page(page_index):
            url = self.standings_url
            if page_index:
                url += f'?page={page_index}'
            n_attempts = 3
            for attempt in range(n_attempts):
                try:
                    page = REQ.get(url)
                    break
                except FailOnGetResponse as e:
                    if e.code == 503 and attempt + 1 < n_attempts:
                        REQ.print(str(e))
                        sleep(5)
                        continue
                    raise e

            return page, url

        place = 0
        idx = 0
        prev = None
        with PoolExecutor(max_workers=4) as executor, tqdm.tqdm(total=n_page, desc='fetch pages') as pbar:
            for page, url in executor.map(fetch_page, range(n_page)):
                pbar.set_postfix(url=url)
                pbar.update(1)

                regex = '<table[^>]*>.*?</table>'
                match = re.search(regex, page, re.DOTALL)
                if not match:
                    continue
                html_table = match.group(0)
                table = parsed_table.ParsedTable(html_table)
                for r in table:
                    idx += 1
                    row = {}
                    problems = row.setdefault('problems', {})
                    for k, v in list(r.items()):
                        k = k.split()[0]
                        if k.lower() == 'score':
                            solving, *a = v.value.split()
                            row['solving'] = int(solving)
                            if a:
                                row['penalty'] = int(re.sub(r'[\(\)]', '', a[0]))
                        elif len(k) == 1:
                            if k not in problems_info:
                                problems_info[k] = {'short': k}
                                title = first(v.header.node.xpath('a[@title]/@title'))
                                url = first(v.header.node.xpath('a[@href]/@href'))
                                if title:
                                    problems_info[k]['name'] = html.unescape(title)
                                if url:
                                    problems_info[k]['url'] = urllib.parse.urljoin(self.standings_url, url)

                            if '-' in v.value or '+' in v.value:
                                p = problems.setdefault(k, {})
                                if ' ' in v.value:
                                    point, time = v.value.split()
                                    p['time'] = time
                                else:
                                    point = v.value
                                if point == '+0':
                                    point = '+'
                                p['result'] = point
                            elif v.value.isdigit():
                                p = problems.setdefault(k, {})
                                p['result'] = v.value
                        elif k.lower() == 'user':
                            row['member'] = v.value
                        else:
                            row[k] = v.value

                    if 'penalty' not in row:
                        solved = [p for p in list(problems.values()) if p['result'] == '100']
                        row['solved'] = {'solving': len(solved)}

                    curr = (row['solving'], row.get('penalty'))
                    if prev is None or prev != curr:
                        place = idx
                        prev = curr
                    row['place'] = place

                    result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    # statictic = Statistic(url='https://www.e-olymp.com/en/contests/13532', standings_url=None)
    # pprint(statictic.get_standings()['problems'])
    statictic = Statistic(url='https://www.e-olymp.com/en/contests/13745', standings_url=None)
    pprint(statictic.get_standings()['problems'])
