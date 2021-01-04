#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import urllib.parse
import json
import time
import zlib
from base64 import b64encode, b64decode
from collections import OrderedDict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import tqdm
import pytz
from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, FailOnGetResponse, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    TIMESTAMP_DELTA = timedelta(hours=4).total_seconds()
    LANGUAGES_MAPPING = {
        '1': 'java',
        '5': 'csharp',
        '20': 'cpp',
        '9': 'python3',
        '7': 'python2',
        '19': 'kotlin',
        '17': 'scala',
        '21': 'go',
        '26': 'rust',
        '28': 'python2',
        # '15': '',
        # '22': '',
        # '11': '',
        # '32': '',
    }

    @staticmethod
    def get(*args, **kwargs):
        n_iterations = 5
        for iteration in range(n_iterations):
            try:
                return REQ.get(*args, **kwargs)
            except FailOnGetResponse as e:
                if e.code == 502 and iteration + 1 < n_iterations:
                    time.sleep(3 + iteration)
                    continue
                raise e

    @staticmethod
    def norm_timestamp(t):
        return t // 1000 - Statistic.TIMESTAMP_DELTA

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url
        standings_url = re.sub('.*/(http.*)', r'\1', standings_url)

        web_archive_url = self.info.get('parse', {}).get('web_archive_url')
        if web_archive_url:
            web_archive_url = re.sub('/http.*', '/', web_archive_url)
            standings_url = web_archive_url + standings_url

        if not web_archive_url and datetime.utcnow().replace(tzinfo=pytz.utc) - self.end_time > timedelta(days=30):
            raise ExceptionParseStandings('Long time passed')

        total_num_pages = None

        codename = self.name.split('.')[0]

        @RateLimiter(max_calls=10, period=1)
        def fetch_table(page):
            nonlocal web_archive_url
            nonlocal total_num_pages
            nonlocal standings_url
            url = standings_url
            if n_page > 1:
                url += f'/page/{page}'
            if not web_archive_url:
                url += '?locale=en'

            page = Statistic.get(url)

            match = re.search('<title>[^<]*-(?P<name>[^<]*)</title>', page)
            if codename not in match.group('name'):
                return

            if total_num_pages is None:
                matches = re.findall(
                    '<span[^>]*class="[^"]*page-index[^"]*"[^>]*pageindex="([0-9]+)"[^>]*>',
                    page,
                    re.I,
                )
                if matches:
                    total_num_pages = int(matches[-1])

            regex = '''<table[^>]*class="[^>]*table[^>]*"[^>]*>.*?</table>'''
            match = re.search(regex, page, re.DOTALL)
            table = parsed_table.ParsedTable(
                match.group(0),
                header_mapping={
                    '№': '#',
                    'Участник': 'Participant',
                    'Бои': 'Games',
                    'Игры': 'Games',
                    'Побед': 'Won',
                    'Рейтинг': 'Rating',
                    'Язык': 'Language',
                },
            )
            return table

        result = {}
        n_page = 1
        ok = True
        last_rating = None
        while ok and (not users or len(users) != len(result)):
            ok = False
            table = fetch_table(n_page)
            if table is None:
                break

            for row in table:
                r = OrderedDict()

                participant = row.pop('Participant')
                member = participant.value
                if member in result or users and member not in users:
                    continue
                r['member'] = member
                if not web_archive_url:
                    r['info'] = {'avatar': participant.column.node.xpath('.//img/@src')[0]}
                url = participant.column.node.xpath('.//a/@href')[0]
                r['url'] = urllib.parse.urljoin(standings_url, url)

                r['place'] = int(row.pop('#').value)
                score = int(row.pop('Rating').value)
                r['solving'] = score
                r['delta'] = last_rating - score if last_rating is not None else ''
                last_rating = score

                if 'Language' in row:
                    classes = row.pop('Language').column.node.xpath('.//*[contains(@class, "lc")]/@class')
                    if classes:
                        prefix = 'LangIc-'
                        language = None
                        for cls in classes[0].split():
                            if cls.startswith(prefix):
                                language = cls[len(prefix):]
                        if language:
                            r['language'] = Statistic.LANGUAGES_MAPPING.get(language, language)

                r['games'] = row.pop('Games').value.split()[-1]

                row.pop('Δ', None)
                for k, v in list(row.items()):
                    r[k.strip().lower()] = v.value

                result[member] = r
                ok = True
            n_page += 1

            if total_num_pages is None or n_page >= total_num_pages:
                break

        def fetch_rating(row):
            member = row['member']
            if not statistics or member not in statistics:
                return
            user_id = statistics[member].get('_user_id')
            if not user_id:
                page = Statistic.get(row['url'])
                match = re.search(r'userId\s*:\s*(?P<user_id>[0-9]+)', page)
                user_id = match.group('user_id')

            row['_user_id'] = user_id
            post = {
                'action': 'getRatingChanges',
                'userId': user_id,
                'mode': 'ALL',
                'csrf_token': csrf_token,
            }
            page = Statistic.get('/data/ratingChangeDataPage', post=post)
            rating_changes = json.loads(page)
            rating_data = {}

            ratings = rating_changes.get('ratingChanges')
            if ratings:
                ratings = json.loads(ratings)
                rating_data['ratings'] = ratings
                if ratings and len(ratings) > 1:
                    ema = 0
                    prev = None
                    alpha = 0.1
                    for rating in ratings:
                        if prev is not None:
                            ema += ((rating['rating'] - prev) - ema) * alpha
                        prev = rating['rating']
                    row[f'delta_ema={alpha}'] = f'{ema:.2f}'
                row['new_rating'] = ratings[-1]['rating']

            submissions = rating_changes.get('submissions')
            if submissions:
                submissions = json.loads(submissions)
                rating_data['submissions'] = submissions
                row['created'] = Statistic.norm_timestamp(submissions[0]['time'])
                row['updated'] = Statistic.norm_timestamp(submissions[-1]['time'])
                row['version'] = len(submissions)

            rating_data_str = json.dumps(rating_data)
            rating_data_zip = zlib.compress(rating_data_str.encode('utf-8'))
            rating_data_b64 = b64encode(rating_data_zip).decode('ascii')
            row['_rating_data'] = rating_data_b64

        if not web_archive_url and '/1/' in self.standings_url:
            match = re.search('<meta[^>]*name="x-csrf-token"[^>]*content="(?P<token>[^"]*)"[^>]*>', REQ.last_page, re.I)
            csrf_token = match.group('token')

            with PoolExecutor(max_workers=8) as executor:
                for _ in tqdm.tqdm(executor.map(fetch_rating, result.values()), desc='ratings'):
                    pass

        ret = {
            'result': result,
            'url': standings_url,
            'fields_types': {'updated': ['timestamp'], 'created': ['timestamp']},
            'hidden_fields': ['new_rating', 'version', 'created'],
        }

        if self.name.endswith('Finals'):
            ret['options'] = {
                'medals': [
                    {'name': 'gold', 'count': 1},
                    {'name': 'silver', 'count': 1},
                    {'name': 'bronze', 'count': 1},
                    {'name': 'honorable', 'count': 3},
                ]
            }

        return ret

    @staticmethod
    def get_users_infos(users, resource=None, accounts=None, pbar=None):

        @RateLimiter(max_calls=10, period=1)
        def fetch_profile(user):
            url = resource.profile_url.format(account=user)
            url += '?locale=en'
            try:
                page = Statistic.get(url)
            except FailOnGetResponse:
                return {}
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
                path = urllib.parse.urlparse(Statistic.get(url, return_last_url=True)).path
                return None if path == '/' else {}
            ret = {'name': match.group('name').strip()}
            location = match.group('location')
            if location:
                country = re.split('<br/?>', location)[-1].strip()
                ret['country'] = country

            match = re.search('<a[^>]*class="userFace"[^>]*>[^<]*<img[^>]*src="(?P<url>[^"]*)"', page)
            if match:
                ret['avatar'] = urllib.parse.urljoin(url, match.group('url'))

            match = re.search(r'userId\s*:\s*(?P<user_id>[0-9]+)', page)
            ret['_user_id'] = match.group('user_id')
            return ret

        with PoolExecutor(max_workers=4) as executor:
            for data in executor.map(fetch_profile, users):
                if pbar:
                    pbar.update()
                if not data and data is not None:
                    yield {'skip': True}
                else:
                    yield {'info': data}

    @staticmethod
    def get_rating_history(rating_data, stat, resource):
        rating_data_zip = b64decode(rating_data.encode('ascii'))
        rating_data_str = zlib.decompress(rating_data_zip).decode('utf-8')
        rating_data = json.loads(rating_data_str)
        ratings = rating_data['ratings']
        ret = []
        prev = None
        for rating in ratings:
            timestamp = Statistic.norm_timestamp(rating['time'])
            date = datetime.utcnow().fromtimestamp(timestamp).replace(tzinfo=pytz.utc)

            if rating['gameId'] < 0:
                continue

            r = {
                'date': date,
                'date_format': '%H:%M, %b %-d, %Y',
                'new_rating': rating['rating'],
                'name': f"{stat['name']}#{rating['gameId']}",
                'url': urllib.parse.urljoin(resource.url, f"/game/view/{rating['gameId']}"),
            }
            if prev is not None:
                r['old_rating'] = prev
                r['rating_change'] = rating['rating'] - prev
            prev = rating['rating']

            ret.append(r)

        return ret
