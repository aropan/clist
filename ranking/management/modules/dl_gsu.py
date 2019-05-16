# -*- coding: utf-8 -*-

from common import REQ, BaseModule, parsed_table
from excepts import InitModuleException, ExceptionParseStandings

import re
from urllib.parse import urljoin
from pprint import pprint  # noqa


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        if not self.name or not self.start_time or not self.url:
            raise InitModuleException()

    def get_standings(self, users=None):
        if not self.standings_url:
            page = REQ.get(urljoin(self.url, '/'))

            for name in (
                'Соревнования',
                'Тренировочные олимпиады',
                'Результаты прошедших тренировок',
            ):
                match = re.search('<a[^>]*href="(?P<url>[^"]*)"[^>]*>{}<'.format(name), page)
                page = REQ.get(match.group('url'))

            date = self.start_time.strftime('%Y-%m-%d')
            matches = re.findall(r'''
                <tr[^>]*>[^<]*<td[^>]*>{}</td>[^<]*
                <td[^>]*>(?P<title>[^<]*)</td>[^<]*
                <td[^>]*>[^<]*<a[^>]*href\s*=["\s]*(?P<url>[^">]*)["\s]*[^>]*>
            '''.format(date), page, re.MULTILINE | re.VERBOSE)

            urls = [
                url for title, url in matches
                if not re.search(r'[0-9]\s*-\s*[0-9].*[0-9]\s*-\s*[0-9].*\bкл\b', title)
            ]

            if not urls or len(urls) > 1:
                raise ExceptionParseStandings('Not found or too much standing url')

            page = REQ.get(urls[0])
            self.standings_url = REQ.last_url
        else:
            page = REQ.get(self.standings_url)

        html_table = re.search('<table[^>]*bgcolor="silver"[^>]*>.*?</table>', page, re.MULTILINE | re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)

        result = {}
        for r in table:
            row = {}
            problems = row.setdefault('problems', {})
            solved = 0
            for k, v in list(r.items()):
                if k == 'Имя':
                    href = v.column.node.xpath('a/@href')
                    if not href:
                        continue
                    uid = re.search('[0-9]+$', href[0]).group(0)
                    row['member'] = uid
                    row['name'] = v.value
                elif k == 'Место':
                    row['place'] = v.value
                elif k == 'Сумма':
                    row['solving'] = v.value
                elif len(k) == 1 and v.value:
                    p = problems.setdefault(k, {})
                    p['name'] = k
                    p['result'] = v.value
                    if '+' in v.value or v.value == '100':
                        solved += 1
            row['solved'] = {'solving': solved}
            result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
        }

        return standings


if __name__ == '__main__':
    import sys
    import os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from clist.models import Contest

    from django.utils import timezone

    contest = Contest.objects \
        .filter(host='dl.gsu.by', end_time__lt=timezone.now() - timezone.timedelta(days=2)) \
        .order_by('start_time') \
        .last()

    statistic = Statistic(
        name=contest.title,
        url=contest.url,
        key=contest.key,
        standings_url=contest.standings_url,
        start_time=contest.start_time,
    )

    pprint(statistic.get_standings())
