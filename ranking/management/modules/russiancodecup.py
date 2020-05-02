#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
from tqdm import tqdm
from pprint import pprint
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            name = self.name.lower().replace('-', '')
            info = None
            for lang in 'ru', 'en':
                url = f'https://www.russiancodecup.ru/{lang}/ajax/rounds_filter/'
                page = REQ.get(url)
                match = re.search(r"parseJSON\('(?P<data>[^']*)'\)", page)
                data = json.loads(match.group('data'))
                data = data[f'RCC {self.start_time.year}']

                for r in data:
                    if info is None:
                        ok = True
                        for w in r['NAME'].split():
                            w = w.lower().replace('-', '')
                            if w not in name:
                                ok = False
                                break
                        if ok:
                            info = r
                            break
                    else:
                        if info['CODE'] == r['CODE']:
                            info = r
                            break
            self.standings_url = f'https://www.russiancodecup.ru/en/results/championship/round/{info["ID"]}/'
            self.name = info['NAME']

        match = re.search('/round/([0-9]+)/', self.standings_url)
        rid = match.group(1)

        result = OrderedDict()
        problems_info = OrderedDict()

        n_page = 1
        pbar = None
        total = None
        users = []
        while total is None or n_page <= total:
            url = f'https://www.russiancodecup.ru/en/ajax/result/{rid}/?page={n_page}'
            page = REQ.get(url)
            data = json.loads(page)
            if pbar is None:
                total = int(data['countPage'] + 1e-9)
                pbar = tqdm(total=total, desc='paging')

            for row in data['data']:
                handle = row['user']['UF_NICKNAME']
                r = result.setdefault(handle, OrderedDict())
                r['member'] = handle
                r['place'] = row.pop('rank')
                r['penalty'] = row.pop('penalty')
                r['solving'] = row.pop('solved')
                r['name'] = f"{row['user']['LAST_NAME']} {row['user']['NAME']}"
                if 'qualification' in row:
                    r['advanced'] = row['qualification']
                problems = r.setdefault('problems', {})
                for k, v in row['problems'].items():
                    if k not in problems_info:
                        problems_info[k] = {'short': k}

                    attempts = v.pop('attempts')
                    if not attempts:
                        continue
                    p = problems.setdefault(k, {})
                    penalty = v.pop('penalty')
                    if penalty:
                        p['time'] = penalty
                    if v['solved'] == 'yes':
                        p['result'] = '+' if attempts == 1 else f'+{attempts - 1}'
                    else:
                        p['result'] = f'-{attempts}'
                if not problems:
                    result.pop(handle)
                    continue
                users.append({
                    'id': row['user']['ID'],
                    'handle': handle,
                })

            n_page += 1
            pbar.update()
        pbar.close()

        @RateLimiter(max_calls=10, period=1)
        def fetch_info(user):
            url = f'https://www.russiancodecup.ru/en/ajax/user/{user["id"]}'
            page = REQ.get(url)
            matches = re.finditer('<tr><th>(?P<key>[^<]*):</th><td>(?P<value>[^<]*)</td></tr>', page)
            info = {}
            for match in matches:
                key = match.group('key').strip().lower()
                if key == 'about yourself':
                    continue
                value = match.group('value').strip()
                info[key] = value
            return user, info

        with PoolExecutor(max_workers=8) as executor:
            for user, info in tqdm(executor.map(fetch_info, users), total=len(users), desc='fetching info'):
                result[user['handle']].update(info)

        standings = {
            'title': self.name,
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }

        if re.search(r'\bfinals?\b', self.name, re.I):
            standings['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}

        return standings


def run():
    from clist.models import Contest
    qs = Contest.objects.filter(resource__host__regex='russiancodecup').order_by('start_time')

    for contest in qs:
        statictic = Statistic(contest=contest)
        standings = statictic.get_standings()
        standings.pop('result', None)
        pprint(standings)
        break
