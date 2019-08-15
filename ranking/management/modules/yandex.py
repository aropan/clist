# -*- coding: utf-8 -*-

import re
import os
from collections import OrderedDict
from urllib.parse import urljoin


from common import REQ, BaseModule, parsed_table


class Statistic(BaseModule):
    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        if not self.standings_url:
            self.standings_url = os.path.join(re.sub('enter/?', '', self.url), 'standings')

    def get_standings(self, users=None):
        result = {}
        problems_info = OrderedDict()

        if not re.search('/[0-9]+/', self.standings_url):
            return {}

        url = self.standings_url
        n_page = 1
        while True:
            page = REQ.get(url)

            html_table = re.search(
                '<table[^>]*class="[^"]*standings[^>]*>.*?</table>',
                page,
                re.MULTILINE | re.DOTALL
            ).group(0)

            table = parsed_table.ParsedTable(html_table)

            for r in table:
                row = {}
                problems = row.setdefault('problems', {})
                solved = 0
                for k, v in list(r.items()):
                    if 'table__cell_role_result' in v.attrs['class']:
                        letter = k.split(' ', 1)[0]
                        if letter == 'X':
                            continue

                        p = problems_info.setdefault(letter, {'short': letter})
                        names = v.header.node.xpath('.//span/@title')
                        if len(names) == 1:
                            p['name'] = names[0]

                        p = problems.setdefault(letter, {})
                        n = v.column.node
                        if n.xpath('img[contains(@class,"image_type_success")]'):
                            res = '+'
                            p['binary'] = True
                        elif n.xpath('img[contains(@class,"image_type_fail")]'):
                            res = '-'
                            p['binary'] = False
                        else:
                            if ' ' not in v.value:
                                problems.pop(letter)
                                continue
                            res = v.value.split(' ', 1)[0]
                        p['result'] = res
                        p['time'] = v.value.split(' ', 1)[-1]
                        if '+' in res or res.startswith('100'):
                            solved += 1
                    elif 'table__cell_role_participant' in v.attrs['class']:
                        row['member'] = v.value.replace(' ', '', 1)
                    elif 'table__cell_role_place' in v.attrs['class']:
                        row['place'] = v.value
                    elif 'table__header_type_penalty' in v.attrs['class']:
                        row['penalty'] = v.value
                    elif 'table__header_type_score' in v.attrs['class']:
                        row['solving'] = int(round(float(v.value)))
                row['solved'] = {'solving': solved}
                result[row['member']] = row

            n_page += 1
            match = re.search(f'<a[^>]*href="(?P<href>[^"]*standings[^"]*p[^"]*={n_page})"[^>]*>', page)
            if not match:
                break
            url = urljoin(url, match.group('href'))

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }
        return standings


if __name__ == "__main__":
    from pprint import pprint
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from clist.models import Contest
    from django.utils.timezone import now

    contest = Contest.objects.filter(host='contests.snarknews.info', end_time__lte=now()).last()

    statistic = Statistic(
        name=contest.title,
        url=contest.url,
        key=contest.key,
        standings_url=contest.standings_url,
        start_time=contest.start_time,
    )
    s = statistic.get_standings()
    pprint(len(s['result']))
    pprint(s['problems'])
