#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ
from common import BaseModule, parsed_table
from first import first


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = self.url.replace('contest.aspx', 'monitor.aspx')

    def get_standings(self, users=None):
        result = {}

        page = REQ.get(self.standings_url)
        table = parsed_table.ParsedTable(html=page, xpath="//table[@class='monitor']//tr")
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            for k, v in list(r.items()):
                title = first(v.header.node.xpath('a[@title]/@title'))
                if k in ['Участник', 'Participant']:
                    row['member'] = v.value
                elif k in ['Место', 'Rank']:
                    row['place'] = v.value
                elif k in ['Время', 'Time']:
                    row['penalty'] = int(v.value)
                elif k in ['Решено', 'Solved']:
                    row['solving'] = int(v.value)
                elif len(k) == 1 and v.value and title is not None:
                    p = problems.setdefault(k, {})
                    values = v.value.replace('–', '-').split(' ')
                    p['name'] = title
                    p['result'] = values[0]
                    if len(values) > 1:
                        p['time'] = values[1]
            result[row['member']] = row
        standings = {
            'result': result,
            'url': self.standings_url,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='Later is better than never',
        url='http://acm.timus.ru/contest.aspx?id=423',
        standings_url=None,
        key='http://acm.timus.ru/contest.aspx?id=423',
    )
    from pprint import pprint
    pprint(statictic.get_standings())
