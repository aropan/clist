#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import urllib.parse
import re

from first import first

from ranking.management.modules.common import REQ
from ranking.management.modules.common import BaseModule, parsed_table


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = self.url.replace('contest.aspx', 'monitor.aspx')

    def get_standings(self, users=None, statistics=None):
        result = {}

        page = REQ.get(self.standings_url + ('&' if '?' in self.standings_url else '?') + 'locale=en')
        table = parsed_table.ParsedTable(html=page, xpath="//table[@class='monitor']//tr")
        problems_info = collections.OrderedDict()
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                title = first(v.header.node.xpath('a[@title]/@title'))
                if k in ['Участник', 'Participant']:
                    url = first(v.column.node.xpath('a[@href]/@href'))
                    row['member'] = re.search('([0-9]+)/?$', url).group(1)
                    row['name'] = v.value
                elif k in ['Место', 'Rank']:
                    row['place'] = v.value
                elif k in ['Время', 'Time']:
                    row['penalty'] = int(v.value)
                elif k in ['Решено', 'Solved']:
                    row['solving'] = int(v.value)
                elif len(k) == 1 and title is not None:
                    problems_info[k] = {'short': k, 'name': title}
                    url = first(v.header.node.xpath('a[@href]/@href'))
                    if url is not None:
                        problems_info[k]['url'] = urllib.parse.urljoin(self.standings_url, url)
                    if v.value:
                        p = problems.setdefault(k, {})
                        values = v.value.replace('–', '-').split(' ')
                        p['result'] = values[0]
                        if len(values) > 1:
                            p['time'] = values[1]
            result[row['member']] = row
        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


