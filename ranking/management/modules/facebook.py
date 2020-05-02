#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import re
import warnings
import html
from tqdm import tqdm
from urllib.parse import urljoin
from pprint import pprint
from collections import OrderedDict

import googlesearch

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            year = self.start_time.year
            name = re.sub(r'(online|onsite)\s+', '', self.name, flags=re.I).strip()
            query = f'site:https://www.facebook.com/hackercup/round/* Facebook Hacker Cup {year} {name}'
            urls = list(googlesearch.search(query, stop=2))
            if len(urls) == 1:
                self.standings_url = urls[0].replace('/round/', '/scoreboard/')
        if not self.standings_url:
            raise ExceptionParseStandings('not found standing url')

        offset = 0
        limit = 100

        result = OrderedDict()

        pbar = None
        total = None
        title = None
        problems_info = None
        while limit:
            url = f'{self.standings_url}?offset={offset}&length={limit}'
            page = REQ.get(url)

            match = re.search(r'"problemData":(?P<data>\[[^\]]*\])', page, re.I)
            if not match:
                limit //= 2
                continue

            problem_data = json.loads(match.group('data'))
            if problems_info is None:
                matches = re.finditer(r'<div[^>]*class="linkWrap noCount"[^>]*>(?P<score>[0-9]+):\s*(?P<title>[^<]*)',
                                      page)
                problems_scores = {}
                for match in matches:
                    score = int(match.group('score'))
                    name = html.unescape(match.group('title')).strip()
                    problems_scores[name] = score

                problems_info = []
                for problem in problem_data:
                    name = str(problem['name']).strip()
                    problems_info.append({
                        'code': str(problem['id']),
                        'name': name,
                        'full_score': problems_scores[name],
                    })

            if title is None:
                match = re.search('<h2[^>]*class="accessible_elem"[^>]*>(?P<title>[^<]*)</h2>', page)
                title = match.group('title')

            match = re.search(r'"scoreboardData":(?P<data>\[[^\]]*\])', page, re.I)
            data = json.loads(match.group('data'))

            if pbar is None:
                match = re.search(r'"pagerData":(?P<data>{[^}]*})', page, re.I)
                pager = json.loads(match.group('data'))
                total = pager['total']
                pbar = tqdm(total=total, desc='paging')

            for row in data:
                handle = str(row.pop('userID'))
                r = result.setdefault(handle, OrderedDict())

                r['member'] = handle
                r['solving'] = row.pop('score')
                r['place'] = row.pop('rank')
                r['name'] = row.pop('profile')['name']

                penalty = row.pop('penalty')
                if penalty:
                    r['penalty'] = self.to_time(penalty)

                problems = r.setdefault('problems', {})
                solved = 0
                for k, v in row.pop('problemData').items():
                    verdict = v.get('result')
                    if not verdict or verdict == 'none':
                        continue
                    p = problems.setdefault(k, {})
                    if verdict == 'accepted':
                        p['result'] = '+'
                        p['binary'] = True
                        solved += 1
                    else:
                        p['result'] = '0'
                        p['verdict'] = verdict
                        p['binary'] = False
                    u = v.get('sourceURI')
                    if v:
                        p['url'] = urljoin(url, u)
                r['solved'] = {'solving': solved}

                pbar.update()
                total -= 1

            if len(data) < limit:
                break

            offset += limit

        pbar.close()

        words = self.name.split()
        words.append(str(self.start_time.year))
        for w in words:
            if w.lower() not in title.lower():
                warnings.warn(f'"{w}" not in title "{title}"')

        if total:
            warnings.warn(f'{total} member(s) did not get')

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
        }

        if re.search(r'\bfinals?\b', self.name, re.I):
            standings['options'] = {'medals': [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]}

        return standings


def run():
    from clist.models import Contest
    qs = Contest.objects.filter(resource__host__regex='facebook').order_by('start_time')

    contest = qs.first()
    print(contest.title, contest.start_time.year)
    statictic = Statistic(contest=contest)
    pprint(statictic.get_standings())
