#!/usr/bin/env python3

import html
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number
# from ranking.management.modules.common.locator import Locator
from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        standings_url = self.url.rstrip('/') + '/results'

        def is_english_locale(page):
            match = re.search('<a[^>]*class="[^"]*font-weight-bold[^"]*"[^>]*>(?P<locale>[^<]+)</a>', page)
            return match.group('locale').lower().strip() == 'english'

        def set_locale():
            return REQ.get(urljoin(standings_url, '/locale/en'))

        def get_page(*args, **kwargs):
            page = REQ.get(*args, **kwargs)
            if not is_english_locale(page):
                page = set_locale()
                if not is_english_locale(page):
                    raise ExceptionParseStandings('Failed to set locale')
            return page

        problems_infos = OrderedDict()
        result = OrderedDict()

        n_page = 0
        nothing = False
        while not nothing:
            n_page += 1

            page = get_page(standings_url + f'?page={n_page}')
            page = re.sub(r'<!(?:--)?\[[^\]]*\](?:--)?>', '', page)
            table = parsed_table.ParsedTable(page, as_list=True)
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
                    elif f.startswith('fullname'):
                        a = v.column.node.xpath('.//a')[0]
                        r['member'] = re.search('profile/(?P<key>[^/]+)', a.attrib['href']).group('key')
                        r['name'] = html.unescape(a.text).strip()
                        small = v.column.node.xpath('.//small')
                        if small and (text := small[0].text):
                            r['affiliation'] = html.unescape(text).strip()
                    elif not f:
                        i = v.header.node.xpath('.//i')
                        if i:
                            c = i[0].attrib['class']
                            if 'strava' in c:
                                if v.value == '0':
                                    r['rating_change'] = 0
                                elif v.value != '-':
                                    new_rating, rating_change = v.value.split()
                                    r['rating_change'] = int(rating_change)
                                    r['new_rating'] = int(new_rating)
                            elif 'tasks' in c:
                                r['tasks'] = v.value
                    elif f == 'ball':
                        r['solving'] = v.value
                    elif f == 'penalty':
                        r['penalty'] = v.value
                    elif len(f.split()[0]) == 1:
                        short, full_score = f.split()
                        short = short.title()
                        if short not in problems_infos:
                            name = html.unescape(v.header.node.attrib['title'])
                            problems_infos[short] = {
                                'short': short,
                                'name': name or short,
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
                        elif ' / ' in val:
                            res, full = [as_number(v) for v in val.split(' / ')]
                            if 0 < res < full:
                                p['partial'] = True
                            p['result'] = res
                        else:
                            p['result'] = val
                        if 'first-solved' in v.column.node.attrib['class']:
                            p['first_ac'] = True

                if not r.get('member'):
                    continue

                if not problems and not as_number(r['solving']):
                    continue

                result[r['member']] = r
                nothing = False

        problems = list(problems_infos.values())
        for problem in problems:
            problem_page = get_page(problem['url'])
            match = re.search(r'<h[^>]*>\s*Task\s*#(?P<key>[^<]*)</h', problem_page)
            problem['code'] = match.group('key').strip()
            archive_url = self.resource.problem_url.format(key=problem['code'])
            try:
                REQ.head(archive_url)
                problem['archive_url'] = archive_url
            except Exception:
                problem['archive_url'] = None

        ret = {
            'hidden_fields': ['affiliation'],
            'url': standings_url,
            'problems': problems,
            'result': result,
        }

        return ret

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        @RateLimiter(max_calls=5, period=1)
        def fetch_profile(handle):
            url = resource.profile_url.format(account=handle)
            try:
                page = REQ.get(url)
            except FailOnGetResponse as e:
                if e.code == 404:
                    return None
                raise e

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

            match = re.search(r'<h3[^>]*class="[^"]*card-title[^"]*"[^>]*>(?:\s*<[^>]*>)*(?P<name>[^<]*)', page)
            ret['name'] = html.unescape(match.group('name'))

            # for field in 'region', 'district':
            #     if ret.get(field):
            #         country = locator.get_country(ret[field], lang='ru')
            #         if country:
            #             ret['country'] = country
            #             break

            return ret

        # with PoolExecutor(max_workers=8) as executor, Locator() as locator:
        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                if not data:
                    if data is None:
                        yield {'delete': True}
                    else:
                        yield {'skip': True}
                    continue

                ret = {
                    'info': data,
                    'replace_info': True,
                }

                yield ret
