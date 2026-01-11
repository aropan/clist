#!/usr/bin/env python

import html
import re
from collections import OrderedDict
from datetime import timedelta
from pprint import pprint

from django.utils.timezone import now

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import FailOnGetResponse, InitModuleException
from ranking.management.modules.nerc_itmo_helper import parse_xml


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None, statistics=None, **kwargs):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        result = {}
        problems_info = OrderedDict()

        page = REQ.get(self.standings_url)

        try:
            standings_xml = REQ.get(self.standings_url.replace('.html', '.xml'), detect_charsets=False)
            xml_result = parse_xml(standings_xml)
        except FailOnGetResponse:
            xml_result = {}

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if not match:
            page = re.sub('<table[^>]*wrapper[^>]*>', '', page)
            regex = '<table[^>]*>.*?</table>'
            match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table, as_list=True)

        university_regex = self.info.get('standings', {}).get('1st_u', {}).get('regex')
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in r:
                k = k.split()[0]
                if k == 'Total' or k == '=':
                    row['solving'] = as_number(v.value)
                elif len(k) <= 3:
                    problems_info[k] = {'short': k}
                    if 'title' in v.attrs:
                        problems_info[k]['name'] = v.attrs['title']

                    if '-' in v.value or '+' in v.value or '?' in v.value:
                        p = problems.setdefault(k, {})
                        if ' ' in v.value:
                            point, time = v.value.split()
                        else:
                            point = v.value
                            time = None
                        if 'result' in p and point != p.get('result'):
                            p.clear()
                        p['result'] = point
                        if time is not None:
                            p['time'] = time

                        first_ac = v.column.node.xpath('.//*[@class="first-to-solve"]')
                        if len(first_ac):
                            p['first_ac'] = True
                elif k == 'Time':
                    row['penalty'] = as_number(v.value)
                elif k.lower() in ['place', 'rank']:
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    if xml_result and v.value in xml_result:
                        problems.update(xml_result[v.value])
                    row['member'] = v.value + ' ' + season
                    row['name'] = v.value
                else:
                    row[k] = v.value
            for f in 'diploma', 'medal', 'qual':
                value = row.pop(f, None) or row.pop(f.title(), None)
                if not value:
                    continue
                words = value.split()
                skipped = []
                for w in words:
                    if w in ['З', 'G']:
                        row['medal'] = 'gold'
                    elif w in ['С', 'S']:
                        row['medal'] = 'silver'
                    elif w in ['Б', 'B']:
                        row['medal'] = 'bronze'
                    elif w in ['I', 'II', 'III']:
                        row['diploma'] = w
                    elif w in ['Q']:
                        row['advanced'] = True
                    else:
                        skipped.append(w)
                if 'diploma' in row and 'medal' not in row:
                    row.update({
                        "medal": "Diploma",
                        "_medal_title_field": "diploma"
                    })
                if skipped:
                    row['_{f}'] = ' '.join(skipped)
            if university_regex:
                match = re.search(university_regex, row['name'])
                if match:
                    u = match.group('key').strip()
                    row['university'] = u
            result[row['member']] = row

        if self.info.get('use_icpc.kimden.online') and self.end_time + timedelta(days=10) > now():
            team_regions = {}

            def canonize_name(name):
                name = re.sub(r'^\*\s*', '', name)
                name = re.sub(':', '', name)
                name = re.sub(r'\s+', '', name)
                return name

            def get_region(team_name):
                nonlocal team_regions
                if team_regions is False:
                    return ''
                if not team_regions:
                    page = REQ.get(self.info['use_icpc.kimden.online'])
                    matches = re.finditer(
                        '<label[^>]*for="(?P<selector>[^"]*)"[^"]*onclick="setRegion[^"]*"[^>]*>(?P<name>[^>]*)</',
                        page,
                    )
                    regions = {}
                    for match in matches:
                        selector = match.group('selector').replace('selector', '').replace('--', '-')
                        regions[selector] = match.group('name')
                    pprint(regions)

                    matches = re.finditer(
                        r'''
                        <tr[^>]*class="(?P<class>[^"]*)"[^>]*>\s*<td[^>]*>[^<]*</td>\s*<td[^>]*title="(?P<name>[^"]*)">
                        ''',
                        page,
                        re.VERBOSE,
                    )

                    for match in matches:
                        classes = match.group('class').split()
                        name = match.group('name')
                        name = html.unescape(name)
                        name = canonize_name(name)
                        for c in classes:
                            if c in regions:
                                team_regions[name] = regions[c]
                                break
                    if not team_regions:
                        team_regions = False
                team_name = canonize_name(team_name)
                return team_regions.get(team_name, '')

            for row in result.values():
                stat = (statistics or {}).get(row['member'])
                if stat and 'region' in stat:
                    row['region'] = stat['region']
                else:
                    row['region'] = get_region(row['name'])

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'problems_time_format': '{M}:{s:02d}',
            'hidden_fields': ['university', 'region', 'medal', 'diploma'],
        }
        if series := self.info.get('series'):
            standings['series'] = series
        return standings
