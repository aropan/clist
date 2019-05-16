# -*- coding: utf-8 -*-

from common import REQ, BaseModule
from excepts import InitModuleException, ExceptionParseStandings

import re
from pprint import pprint  # noqa
from collections import defaultdict


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        if not self.name or not self.url:
            raise InitModuleException()

        match = re.search(r'\b[0-9]{4}\b', self.key)
        if not match:
            raise InitModuleException('Not found year')
        self.year = int(match.group())

    def get_standings(self, users=None):
        if self.standings_url:
            standings_url = self.standings_url
        else:
            page = REQ.get(self.url)
            try:
                contest = re.search(r'<td[^<]*>\s*<div[^>]*>%s</div>.*?</td>' % self.name, page, re.DOTALL).group()
                standings_url = re.search(r'<a[^>]*href="(?P<href>[^"]*)"[^>]*>.*Result.*</a>', contest).group('href')
            except Exception:
                raise ExceptionParseStandings('Not found result url')

        page = REQ.get(standings_url)
        standings_url = REQ.ref_url

        result = {}
        header = None
        problems_max_score = defaultdict(int)
        for match in re.findall(r'<tr[^>]*>.*?<\/tr>', page, re.DOTALL):
            match = match.replace('&nbsp;', ' ')

            member = None
            fields = []
            problem_names = []

            tds = re.finditer(r'<t[hd][^>]*>(?P<td>.*?)<\/t[hd]>', match)
            for i, td in enumerate(tds):
                td = td.group('td')
                value = re.sub('<[^>]*>', '', td)

                attrs = dict(m.group('key', 'value') for m in re.finditer('(?P<key>[a-z]*)="(?P<value>[^"]*)"', td))
                value = attrs.get('title', value)

                if 'href' in attrs:
                    match = re.search('solutions/(?P<member>[^/]*)/', attrs['href'])
                    if match:
                        member = match.group('member')
                        problem_names.append(i)
                fields.append(value)

            if not header:
                header = fields
                continue
            if not member:
                raise ExceptionParseStandings('Not found member')

            row = dict(list(zip(header, fields)))

            r = result.setdefault(member, {})
            r['member'] = member
            r['place'] = row['RANK']
            r['country'] = row['COUNTRY']
            r['solving'] = row['SCORE']

            problems = r.setdefault('problems', {})
            for k in problem_names:
                k = header[k]
                if re.match('^[0-9]+$', row[k]):
                    p = problems.setdefault(k, {})
                    p['result'] = row[k]
                    problems_max_score[k] = max(problems_max_score[k], int(row[k]))
            if not problems:
                r.pop('problems')

        for v in result.values():
            solving = 0
            for k, r in v['problems'].items():
                if problems_max_score[k] == int(r.get('result', -1)):
                    solving += 1
            v['solved'] = {'solving': solving}

        standings = {
            'result': result,
            'url': standings_url,
        }
        return standings


if __name__ == '__main__':
    pprint(Statistic(
        name='CONTEST #5',
        url='http://hsin.hr/coci/',
        key='2018-2019 CO',
        standings_url=None,
    ).get_standings())
