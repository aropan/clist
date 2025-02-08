#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        try:
            page = REQ.get(self.url)
        except FailOnGetResponse as e:
            return {'action': 'delete'} if e.code == 404 else {}

        match = re.search('<table[^>]*past_event_rating[^>]*>.*?</table>', page, re.DOTALL)
        if not match:
            raise ExceptionParseStandings('not found table')

        header_mapping = {
            'Team': 'name',
            'Place': 'place',
            'CTF points': 'solving',
        }
        table = parsed_table.ParsedTable(html=match.group(0), header_mapping=header_mapping)

        results = {}
        max_score = 0
        for r in table:
            row = OrderedDict()
            for k, v in r.items():
                k = k.strip('*')
                k = k.strip(' ')
                value = ' '.join([c.value for c in v]).strip() if isinstance(v, list) else v.value
                if k == 'name':
                    href = v.column.node.xpath('.//a/@href')[0]
                    match = re.search('/([0-9]+)/?$', href)
                    row['member'] = match.group(1)
                    row['name'] = value
                else:
                    value = as_number(value)
                row[k] = value
            max_score = max(max_score, row.get('solving', 0))
            results[row['member']] = row

        if max_score > 0:
            for row in results.values():
                if 'solving' in row:
                    row['percent'] = f'{row["solving"] * 100 / max_score:.2f}'

        options = {}
        has_medals = not re.search(r'\bqual', self.name, flags=re.I) and re.search(r'\bfinal', self.name, flags=re.I)
        if has_medals:
            options['medals'] = [{'name': 'gold', 'count': 1}]

        return dict(
            standings_url=self.url,
            result=results,
            options=options,
        )

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=8, period=1)
        def fetch_user(user, account):
            try:
                url = resource.profile_url.format(account=user)
                page = REQ.get(url)
                page = html.unescape(page)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return user, None
                return user, False

            info = {}
            match = re.search(r'<div[^>]*class="page-header"[^>]*>\s*<h2[^>]*>(?P<name>[^<]*)<', page)
            if match:
                info['name'] = match.group('name')
            match = re.search(r'<h2[^>]*>\s*<img[^>]*alt="(?P<country>[^"]*)"[^>]*>\s*(?P<name>[^<]*)<', page)
            if match:
                info['country'] = match.group('country')
                info['name'] = match.group('name')
            match = re.search(r'<img[^>]*src="(?P<img>[^"]*)"(?:[^>]*(?:width|height)="[^"]*"){2}[^>]*>\s*<br[^>]*>', page)  # noqa
            if match:
                info['avatar_url'] = urljoin(url, match.group('img'))
            return user, info

        with PoolExecutor(max_workers=6) as executor:
            for user, info in executor.map(fetch_user, users, accounts):
                if pbar:
                    pbar.update()
                if not info:
                    if info is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue
                info = {'info': info}
                yield info
