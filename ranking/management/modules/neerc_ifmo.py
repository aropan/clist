#!/usr/bin/env python

import re
from collections import OrderedDict
from datetime import datetime
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import InitModuleException
from ranking.management.modules.neerc_ifmo_helper import parse_xml


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

    def get_standings(self, users=None, statistics=None):
        year = self.start_time.year
        year = year if self.start_time.month >= 9 else year - 1
        season = '%d-%d' % (year, year + 1)

        result = {}
        problems_info = OrderedDict()

        try:
            standings_xml = REQ.get(self.standings_url.replace('.html', '.xml'), detect_charsets=False)
            xml_result = parse_xml(standings_xml)
        except FailOnGetResponse:
            xml_result = {}

        page = REQ.get(self.standings_url)

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if not match:
            page = re.sub('<table[^>]*wrapper[^>]*>', '', page)
            regex = '<table[^>]*>.*?</table>'
            match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)

        university_regex = self.info.get('standings', {}).get('1st_u', {}).get('regex')
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                k = k.split()[0]
                if k == 'Total' or k == '=':
                    row['solving'] = int(v.value)
                elif len(k) <= 3:
                    problems_info[k] = {'short': k}
                    if 'title' in v.attrs:
                        problems_info[k]['name'] = v.attrs['title']

                    if '-' in v.value or '+' in v.value or '?' in v.value:
                        p = problems.setdefault(k, {})
                        if ' ' in v.value:
                            point, time = v.value.split()
                            p['time'] = time
                        else:
                            point = v.value
                        p['result'] = point

                        first_ac = v.column.node.xpath('.//*[@class="first-to-solve"]')
                        if len(first_ac):
                            p['first_ac'] = True
                elif k == 'Time':
                    row['penalty'] = int(v.value)
                elif k.lower() in ['place', 'rank']:
                    row['place'] = v.value.strip('.')
                elif 'team' in k.lower() or 'name' in k.lower():
                    if xml_result:
                        problems.update(xml_result[v.value])
                    row['member'] = v.value + ' ' + season
                    row['name'] = v.value
                else:
                    row[k] = v.value
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
            if university_regex:
                match = re.search(university_regex, row['name'])
                if match:
                    u = match.group('key').strip()
                    row['university'] = u
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'problems_time_format': '{M}:{s:02d}',
            'hidden_fields': ['university'],
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='ICPC 2019-2020, NEERC - Northern Eurasia Finals',
        standings_url='http://neerc.ifmo.ru/archive/2019/standings.html',
        key='2019-2020 NEERC',
        start_time=datetime.strptime('2019-09-02', '%Y-%m-%d'),
    )
    pprint(statictic.get_result('SPb SU: 25 (Belichenko, Bykov, Petrov) 2019-2020'))
