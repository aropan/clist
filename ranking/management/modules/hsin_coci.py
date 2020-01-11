# -*- coding: utf-8 -*-

import re
import urllib.parse
from pprint import pprint  # noqa
from collections import defaultdict, OrderedDict

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import InitModuleException, ExceptionParseStandings


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
        ret = {}
        if 'archive' not in self.url:
            page = REQ.get(self.url)
            season = self.key.split()[0]
            match = re.search(f'<a[^>]*href="(?P<href>[^"]*)"[^>]*>[^/]*{season}<', page)
            if match:
                self.url = urllib.parse.urljoin(REQ.last_url, match.group('href'))
                self.standings_url = None
                ret['action'] = ('url', self.url)

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
        problems_info = OrderedDict()
        problems_max_score = defaultdict(float)
        for match in re.findall(r'<tr[^>]*>.*?<\/tr>', page, re.DOTALL):
            match = match.replace('&nbsp;', ' ')

            member = None
            fields = []
            problems_data = []

            tds = re.findall(r'<t[hd][^>]*>(?P<td>.*?)<\/t[hd]>', match)
            idx = 0
            for i, td in enumerate(tds):
                value = re.sub('<[^>]*>', '', td)

                attrs = dict(m.group('key', 'value') for m in re.finditer('(?P<key>[a-z]*)="(?P<value>[^"]*)"', td))
                if 'title' in attrs:
                    idx += 1
                    value = (f'{idx}', attrs.get('title', value))

                if 'href' in attrs:
                    match = re.search('solutions/(?P<member>[^/]*)/', attrs['href'])
                    if match:
                        member = match.group('member')
                        problems_data.append((i, urllib.parse.urljoin(standings_url, attrs['href'])))
                fields.append(value)

            if not header:
                header = fields
                problems_info = [{'short': v[0], 'name': v[1]} for v in header if isinstance(v, tuple)]
                continue
            if not member:
                continue

            row = dict(list(zip(header, fields)))

            r = result.setdefault(member, {})
            r['member'] = member
            r['place'] = row['RANK']
            r['country'] = row['COUNTRY']
            r['solving'] = int(float(row['SCORE']))

            problems = r.setdefault('problems', {})
            for pn, url in problems_data:
                short = header[pn][0]
                value = row[header[pn]]
                if re.match('^[0-9.]+$', value):
                    p = problems.setdefault(short, {})
                    p['result'] = value
                    p['url'] = url
                    problems_max_score[short] = max(problems_max_score[short], float(p['result']))

        problems_max_score = dict(problems_max_score)
        for v in result.values():
            solving = 0
            for k, r in v['problems'].items():
                s = float(r.get('result', -1))
                if abs(problems_max_score[k] - s) < 1e-9:
                    solving += 1
                elif s > 1e-9:
                    r['partial'] = True
            v['solved'] = {'solving': solving}

        ret.update({
            'result': result,
            'url': standings_url,
            'problems': problems_info,
        })
        return ret


if __name__ == '__main__':
    pprint(Statistic(
        name='CROATIAN OLYMPIAD IN INFORMATICS',
        url='http://hsin.hr/coci/archive/2013_2014/',
        key='2013-2014 CO',
        standings_url=None,
    ).get_standings())
