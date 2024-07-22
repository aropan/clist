#!/usr/bin/env python3

import re
from collections import OrderedDict

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = '{0.host}judge/en/users/contest/{0.key}'

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = self.STANDING_URL_FORMAT_.format(self)

        page = REQ.get(standings_url)
        page = page.replace('&bullet;', '')
        table = parsed_table.ParsedTable(page, xpath='//table[@id="contest-rank"]//tr')
        problems_infos = OrderedDict()
        result = OrderedDict()
        for row in table:
            r = OrderedDict()
            problems = r.setdefault('problems', {})
            for k, v in row.items():
                f = k.lower()
                if f == '#':
                    if not v.value:
                        break
                    r['place'] = v.value
                elif f == 'contestant':
                    a = v.column.node.xpath('.//a')[0]
                    r['member'] = re.search('profile/(?P<key>[0-9]+)', a.attrib['href']).group('key')
                    r['name'] = a.text
                    em = v.column.node.xpath('.//em')
                    if em:
                        em = em[0].text
                        for val in em.split(','):
                            val = val.strip()
                            if val == '-':
                                continue
                            if re.match('^[-0-9A-Z ]+$', val):
                                r['university'] = val
                            else:
                                r['country'] = val
                elif f == 'total':
                    r['solving'], r['penalty'] = map(as_number, v.value.split())
                elif f:
                    problems_infos.setdefault(k, {'short': k})
                    if v.value:
                        p = problems.setdefault(k, {})
                        attempts, p['time'] = map(int, v.value.split())
                        if v.column.node.xpath('.//*[contains(@class,"c-yes")]'):
                            p['result'] = '+' if attempts == 1 else f'+{attempts - 1}'
                        else:
                            p['result'] = f'-{attempts}'
                        if v.column.node.xpath('.//*[contains(@class,"first-to-solve")]'):
                            p['first_ac'] = True
            if problems and 'member' in r:
                result[r['member']] = r

        ret = {
            'url': standings_url,
            'problems': list(problems_infos.values()),
            'result': result,
        }

        return ret
