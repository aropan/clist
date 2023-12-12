#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import re
from collections import OrderedDict, defaultdict

import tqdm

from ranking.management.modules.common import DOT, REQ, SPACE, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.common.locator import Locator
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.management.modules.nerc_itmo_helper import parse_xml

logging.getLogger('geopy').setLevel(logging.INFO)


class Statistic(BaseModule):
    LOCATION_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.locations.yaml')

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
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
        html_table = re.search(regex, page, re.DOTALL)
        if not html_table:
            regex = '<table[^>]*(?:border[^>]*|cellspacing[^>]*|cellpadding[^>]*){3}>.*?</table>'
            html_table = re.search(regex, page, re.DOTALL)
            if not html_table:
                raise ExceptionParseStandings('Cannot find standings table')
        header_mapping = {
            'Team': 'name',
            'Rank': 'place',
            'R': 'place',
            'Time': 'penalty',
            '=': 'solving',
        }
        table = parsed_table.ParsedTable(html_table.group(0), as_list=True, header_mapping=header_mapping)
        mapping_key = {
            'rank': 'place',
            'rankl': 'place',
            'party': 'name',
            'solved': 'solving',
        }

        with Locator() as locator:
            result = {}
            problems_info = OrderedDict()
            for r in tqdm.tqdm(table):
                row = OrderedDict()
                problems = row.setdefault('problems', {})
                ignore_class = False
                n_problem = 0
                for k, v in r:
                    c = (v.attrs.get('class', '').split() or [''])[0]
                    if ignore_class or len(c) < 2:
                        if not k:
                            continue
                        ignore_class = True
                        if 'name' in row and len(k) == 1 and n_problem is not False:
                            c = 'problem'
                        else:
                            c = k
                    if c in ['problem', 'ioiprob']:
                        if n_problem is not False:
                            n_problem += 1
                        problems_info[k] = {'short': k}
                        if 'title' in v.attrs:
                            problems_info[k]['name'] = v.attrs['title']

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
                        if n_problem:
                            n_problem = False
                        c = mapping_key.get(c, c).lower()
                        row[c] = v.value.strip()
                        if xml_result and c == 'name' and v.value in xml_result:
                            problems.update(xml_result[v.value])

                        if c in ('diploma', 'medal', 'd'):
                            medal = row.pop(c, None)
                            if medal:
                                if medal in ['1', 'З', 'G']:
                                    row['medal'] = 'gold'
                                elif medal in ['2', 'С', 'S']:
                                    row['medal'] = 'silver'
                                elif medal in ['3', 'Б', 'B']:
                                    row['medal'] = 'bronze'
                                else:
                                    row[k.lower()] = medal
                name = row['name']

                if 'penalty' not in row:
                    for regex_info in (
                        r'\s*\((?P<info>[^\)]*)\)\s*$',
                        r',(?P<info>.*)$',
                    ):
                        match = re.search(regex_info, row['name'])
                        if not match:
                            continue

                        row['name'] = row['name'][:match.span()[0]]
                        if ',' in row['name']:
                            row['name'] = re.sub(r'[\s,]+', ' ', row['name'])

                        group_info = match.group('info')

                        infos = [s.strip() for s in group_info.split(',')]

                        loc_infos = []
                        for info in infos:
                            if 'degree' not in row:
                                match = re.match(r'^(?P<class>[0-9]+)(?:\s*класс)?$', info, re.IGNORECASE)
                                if match:
                                    row['degree'] = int(match.group('class'))
                                    continue
                            loc_infos.append(info)

                        if not loc_infos:
                            break

                        n_loc_infos = len(loc_infos)
                        for idx in range(n_loc_infos):
                            loc_info = ', '.join(loc_infos[:n_loc_infos - idx])
                            address = locator.get_address(loc_info, lang='ru')
                            if not address:
                                continue
                            country = locator.get_country(loc_info, lang='ru')
                            if country:
                                row['country'] = country
                            city = locator.get_city(loc_info, lang='ru')
                            if city:
                                row['city'] = city
                            break
                        break

                    solved = [p for p in list(problems.values()) if p['result'] == '100']
                    row['solved'] = {'solving': len(solved)}
                elif re.match('^[0-9]+$', row['penalty']):
                    row['penalty'] = int(row['penalty'])

                if self.resource.info.get('statistics', {}).get('key_as_full_name'):
                    row['member'] = name + ' ' + season
                else:
                    row['member'] = row['name'] + ' ' + season

                addition = (statistics or {}).get(row['member'], {})
                if addition:
                    country = addition.get('country')
                    if country:
                        row.setdefault('country', country)
                    detect_location = self.info.get('_detect_location')
                    if 'country' not in row and detect_location:
                        match = re.search(detect_location['regex'], row['name'])
                        if match:
                            loc = match.group('location')
                            split = detect_location.get('split')
                            locs = loc.split(split) if split else [loc]

                            countries = defaultdict(int)
                            for loc in locs:
                                if detect_location.get('first'):
                                    loc = loc.split()[0]
                                country = locator.get_country(loc, lang='ru')
                                if country:
                                    countries[country] += 1
                            if len(countries) == 1:
                                country = list(countries.keys())[0]
                                row['country'] = country

                result[row['member']] = row

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
        }
        return standings
