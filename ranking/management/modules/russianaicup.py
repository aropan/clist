#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import pytz
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):

        if datetime.utcnow().replace(tzinfo=pytz.utc) - self.end_time > timedelta(days=31):
            raise ExceptionParseStandings('Long time passed')

        @RateLimiter(max_calls=10, period=1)
        def fetch_table(page):
            url = self.standings_url + f'/page/{page}?locale=en'
            page = REQ.get(url)

            regex = '''<table[^>]*class="[^>]*table[^>]*"[^>]*>.*?</table>'''
            match = re.search(regex, page, re.DOTALL)
            table = parsed_table.ParsedTable(match.group(0))

            return table

        result = {}
        n_page = 1
        ok = True
        while ok:
            ok = False
            table = fetch_table(n_page)

            for row in table:
                r = OrderedDict()

                participant = row.pop('Participant')
                r['member'] = participant.value
                if r['member'] in result:
                    continue
                r['info'] = {'avatar': participant.column.node.xpath('.//img/@src')[0]}
                url = participant.column.node.xpath('.//a/@href')[0]
                r['url'] = urllib.parse.urljoin(self.standings_url, url)

                r['place'] = int(row.pop('#').value)
                r['solving'] = int(row.pop('Rating').value)
                r['delta'] = int(row.pop('Δ').value)

                classes = row.pop('Language').column.node.xpath('.//*[contains(@class, "lc")]/@class')
                if classes:
                    prefix = 'LangIc-'
                    for cls in classes[0].split():
                        if cls.startswith(prefix):
                            r['language'] = cls[len(prefix):]

                for k, v in list(row.items()):
                    r[k.lower()] = v.value

                result[r['member']] = r
                ok = True
            n_page += 1

        return {'result': result}

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        @RateLimiter(max_calls=10, period=1)
        def fetch_profile(user):
            url = resource.profile_url.format(account=user)
            page = REQ.get(url + '?locale=en')
            ret = {}
            match = re.search(
                '''
                <div[^>]*class="userInfo"[^>]*>[^<]*
                    <div[^>]class="name"[^>]*>(?P<name>[^<]*)</div>[^<]*
                    (?:<div[^>]*class="location"[^>]*>(?P<location>.*?)</div>)?
                ''',
                page,
                re.VERBOSE
            )
            if not match:
                path = urllib.parse.urlparse(REQ.last_url).path
                return None if path == '/' else {}
            ret = {'name': match.group('name').strip()}
            location = match.group('location')
            if location:
                country = re.sub('<br/?>', ' ', location).strip().split()[-1]
                ret['country'] = country
            return ret

        ret = []
        with PoolExecutor(max_workers=4) as executor:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                ret.append({'info': data})
        return ret
