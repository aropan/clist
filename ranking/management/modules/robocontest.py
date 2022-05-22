#!/usr/bin/env python3

import html
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.common.locator import Locator
from ranking.management.modules.common.parsed_table import ParsedTable


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        standings_url = self.url.rstrip('/') + '/results'

        REQ.get(urljoin(standings_url, '/locale/en'))

        problems_infos = OrderedDict()
        result = OrderedDict()

        n_page = 0
        nothing = False
        while not nothing:
            n_page += 1

            page = REQ.get(standings_url + f'?page={n_page}')
            table = ParsedTable(page, as_list=True)
            nothing = True

            for row in table:
                r = OrderedDict()
                problems = r.setdefault('problems', {})
                for k, v in row:
                    f = k.strip().lower()
                    if f == '#':
                        if not v.value:
                            break
                        r['place'] = v.value
                    elif f == 'fullname':
                        a = v.column.node.xpath('.//a')[0]
                        r['member'] = re.search('profile/(?P<key>[^/]+)', a.attrib['href']).group('key')
                        r['name'] = a.text
                        small = v.column.node.xpath('.//small')
                        if small:
                            r['affiliation'] = html.unescape(small[0].text)
                    elif not f:
                        i = v.header.node.xpath('.//i')
                        if i:
                            c = i[0].attrib['class']
                            if 'strava' in c:
                                if v.value == '0':
                                    r['rating_change'] = '0'
                                elif v.value != '-':
                                    new_rating, rating_change = v.value.split()
                                    r['new_rating'] = int(new_rating)
                                    r['rating_change'] = rating_change
                            elif 'tasks' in c:
                                r['solving'] = v.value
                    elif f == 'ball':
                        r['score'] = v.value
                    elif f == 'penalty':
                        r['penalty'] = v.value
                    elif len(f.split()[0]) == 1:
                        short, full_score = f.split()
                        short = short.title()
                        if short not in problems_infos:
                            problems_infos[short] = {
                                'short': short,
                                'name': html.unescape(v.header.node.attrib['title']),
                                'url': urljoin(standings_url, v.header.node.xpath('.//a/@href')[0]),
                                'full_score': int(full_score),
                            }
                        if not v.value:
                            continue
                        val = v.value
                        p = problems.setdefault(short, {})
                        if val.startswith('+'):
                            p['result'], p['time'] = val.split()
                        elif val == '-':
                            p['result'] = '-1'
                        else:
                            p['result'] = val
                        if 'first-solved' in v.column.node.attrib['class']:
                            p['first_ac'] = True

                if not r.get('member'):
                    continue

                result[r['member']] = r
                nothing = False

        ret = {
            'hidden_fields': ['affiliation'],
            'url': standings_url,
            'problems': list(problems_infos.values()),
            'result': result,
        }

        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_profile(handle):
            url = resource.profile_url.format(account=handle)
            page = REQ.get(url)

            ret = {}
            match = re.search('<img[^>]*src="(?P<avatar>[^"]*)"[^>]*id="avatar"', page)
            if match:
                ret['avatar'] = urljoin(url, match.group('avatar'))

            for regex in (
                r'>(?P<val>[^<]*)</h[123]>\s*<p[^>]*>(?P<key>[^<]*)</p>',
                r'<th[^>]*>(?P<key>[^<]*)</th>\s*<td[^>]*>(?P<val>[^<]*)</td>',
            ):
                matches = re.finditer(regex, page)
                for match in matches:
                    key = match.group('key').strip().lower().replace(' ', '_')
                    val = html.unescape(match.group('val').strip())
                    ret[key] = val

            for field in 'region', 'district':
                if ret.get(field):
                    country = locator.get_country(ret[field], lang='ru')
                    if country:
                        ret['country'] = country
                        break

            return ret

        with PoolExecutor(max_workers=8) as executor, Locator() as locator:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'info': None}
                    else:
                        yield {'skip': True}
                    continue

                ret = {
                    'info': data,
                    'replace_info': True,
                }

                yield ret
