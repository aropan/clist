# -*- coding: utf-8 -*-

import re
import urllib.parse
from collections import OrderedDict
from pprint import pprint  # noqa

from clist.models import Resource
from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        if not self.name or not self.url:
            raise InitModuleException()

        match = re.search(r'\b[0-9]{4}\b', self.key)
        if not match:
            raise InitModuleException('Not found year')
        self.year = int(match.group())

    def get_standings(self, users=None, statistics=None, **kwargs):
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
        standings_url = REQ.last_url

        page = page.replace('&nbsp;', ' ')
        mapping = {
            'RANK': 'place',
            'CONTESTANT': 'name',
            'COUNTRY': 'country',
            'SCORE': 'solving',
        }
        table = parsed_table.ParsedTable(page, as_list=True, header_mapping=mapping, with_not_full_row=True)

        resource = Resource.objects.get(host__regex='coci')

        result = {}
        problems_info = OrderedDict()
        for row in table:
            r = dict()
            problems = r.setdefault('problems', {})
            pid = 0
            solving = 0
            for k, v in row:
                name = v.header.node.xpath('.//acronym/@title')
                if name:
                    name = name[0]
                    pid += 1
                    short = str(pid)
                    problem_info = problems_info.setdefault(short, {'short': short, 'name': name})
                    value = as_number(v.value, force=True)
                    if value is not None:
                        p = problems.setdefault(short, {})
                        solving += value
                        p['result'] = value
                        problem_info['max_score'] = max(problem_info.get('max_score', 0), value)

                        href = v.column.node.xpath('.//a/@href')
                        if href:
                            href = href[0]
                            p['url'] = urllib.parse.urljoin(standings_url, href)
                            match = re.search('solutions/(?P<member>[^/]*)/', href)
                            r['member'] = match.group('member')
                elif k == 'solving':
                    r[k] = as_number(v.value)
                else:
                    r[k] = v.value
            if 'solving' not in r:
                r['solving'] = solving
            if 'member' not in r:
                accounts = resource.account_set.filter(name=r['name']).values('key')
                if len(accounts) == 1:
                    r['member'] = accounts[0]['key']
                else:
                    r['member'] = r['name']
            result[r['member']] = r

        for v in result.values():
            solving = 0
            for k, r in v['problems'].items():
                if abs(problems_info[k]['max_score'] - r['result']) < 1e-9:
                    solving += 1
                elif r['result'] > 1e-9:
                    r['partial'] = True
            v['solved'] = {'solving': solving}

        ret.update({
            'result': result,
            'url': standings_url,
            'problems': list(problems_info.values()),
        })
        return ret
