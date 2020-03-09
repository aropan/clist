#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import logging
from datetime import datetime
from pprint import pprint
from collections import OrderedDict

import yaml
import tqdm
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

from ranking.management.modules.common import REQ, DOT, SPACE, BaseModule, parsed_table, FailOnGetResponse
from ranking.management.modules.neerc_ifmo_helper import parse_xml


logging.getLogger('geopy').setLevel(logging.INFO)


class Statistic(BaseModule):
    LOCATION_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.locations.yaml')

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        geolocator = Nominatim(user_agent="clist.by")
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1, max_retries=3)

        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        if not self.standings_url:
            return {}

        try:
            standings_xml = REQ.get(self.standings_url.replace('.html', '.xml'), detect_charsets=False)
            xml_result = parse_xml(standings_xml)
        except FailOnGetResponse:
            xml_result = {}

        page = REQ.get(self.standings_url)

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)
        mapping_key = {
            'rank': 'place',
            'rankl': 'place',
            'party': 'name',
            'solved': 'solving',
        }

        locations = None
        if os.path.exists(self.LOCATION_CACHE_FILE):
            with open(self.LOCATION_CACHE_FILE, 'r') as fo:
                locations = yaml.safe_load(fo)
        if locations is None:
            locations = {}

        try:
            result = {}
            problems_info = OrderedDict()
            for r in tqdm.tqdm(table):
                row = OrderedDict()
                problems = row.setdefault('problems', {})
                for k, v in list(r.items()):
                    c = v.attrs['class'].split()[0]
                    if c in ['problem', 'ioiprob']:
                        problems_info[k] = {'short': k, 'name': v.attrs['title']}
                        if v.value != DOT:
                            p = problems.setdefault(k, {})

                            first_ac = v.column.node.xpath('.//*[@class="first-to-solve"]')
                            if len(first_ac):
                                p['first_ac'] = True

                            partial = v.column.node.xpath('self::td[@class="ioiprob"]/u')
                            if partial:
                                p['partial'] = True

                            v = v.value
                            if SPACE in v:
                                v, t = v.split(SPACE, 1)
                                p['time'] = t
                            p['result'] = v
                    else:
                        c = mapping_key.get(c, c)
                        row[c] = v.value
                        if xml_result and c == 'name':
                            problems.update(xml_result[v.value])
                if 'penalty' not in row:
                    match = re.search(r'\s*\((?P<info>[^\)]*)\)\s*$', row['name'])
                    if match:
                        row['name'] = row['name'][:match.span()[0]]
                        group_info = match.group('info')
                        if u'класс' in group_info:
                            row['degree'], loc_info = map(str.strip, group_info.split(',', 1))
                        else:
                            loc_info = group_info

                        loc_info = re.sub(r'[.,\s]+', ' ', loc_info).strip().lower()
                        if loc_info not in locations:
                            try:
                                locations[loc_info] = {
                                    'ru': geocode(loc_info, language='ru').address,
                                    'en': geocode(loc_info, language='en').address,
                                }
                            except Exception:
                                locations[loc_info] = None
                        address = locations[loc_info]
                        if address:
                            *_, country = map(str.strip, address['en'].split(','))
                            if country.startswith('The '):
                                country = country[4:]
                            row['country'] = country
                            if ', ' in address['ru']:
                                row['city'], *_ = map(str.strip, address['ru'].split(','))

                    solved = [p for p in list(problems.values()) if p['result'] == '100']
                    row['solved'] = {'solving': len(solved)}
                elif re.match('^[0-9]+$', row['penalty']):
                    row['penalty'] = int(row['penalty'])

                for f in 'diploma', 'medal':
                    medal = row.pop(f, None) or row.pop(f.title(), None)
                    if medal:
                        if medal in ['З', 'G']:
                            row['medal'] = 'gold'
                        elif medal in ['С', 'S']:
                            row['medal'] = 'silver'
                        elif medal in ['Б', 'B']:
                            row['medal'] = 'bronze'
                        break
                row['member'] = row['name'] + ' ' + season
                result[row['member']] = row
        finally:
            with open(self.LOCATION_CACHE_FILE, 'wb') as fo:
                yaml.dump(locations, fo, encoding='utf8', allow_unicode=True)

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        standings_url='http://neerc.ifmo.ru/school/io/archive/20120129/standings-20120129-individual.html',
        start_time=datetime.strptime('20120129', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        standings_url='http://neerc.ifmo.ru/school/io/archive/20190324/standings-20190324-individual.html',
        start_time=datetime.strptime('20190324', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        standings_url='http://neerc.ifmo.ru/school/io/archive/20080510/standings-20080510-advanced.html',
        start_time=datetime.strptime('20080510', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
    statictic = Statistic(
        standings_url='https://nerc.itmo.ru/school/archive/2019-2020/ru-olymp-team-russia-2019-standings.html',
        start_time=datetime.strptime('20191201', '%Y%m%d'),
    )
    pprint(statictic.get_standings())
