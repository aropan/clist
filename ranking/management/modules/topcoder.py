#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ, BaseModule, parsed_table
from excepts import InitModuleException

import re
from urllib.parse import urljoin, parse_qs
from lxml import etree
from datetime import timedelta, datetime


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    @staticmethod
    def _dict_as_number(d):
        ret = {}
        for k, v in d.items():
            k = k.strip().lower().replace(' ', '_')
            if not k or not v or v == 'N/A':
                continue
            if ',' in v:
                v = float(v.replace(',', '.'))
            elif re.match('-?[0-9]+', v):
                v = int(v)
            ret[k] = v
        return ret

    def get_standings(self, users=None):
        result = {}

        start_time = self.start_time.replace(tzinfo=None)

        if not self.standings_url and datetime.now() - start_time < timedelta(days=30):
            re_round_overview = re.compile(
                r'''
(?:<td[^>]*>
    (?:
        [^<]*<a[^>]*href="(?P<url>[^"]*/stat[^"]*rd=(?P<rd>[0-9]+)[^"]*)"[^>]*>(?P<title>[^<]*)</a>[^<]*|
        (?P<date>[0-9]+\.[0-9]+\.[0-9]+)
    )</td>[^<]*
){2}
                ''',
                re.VERBOSE,
            )
            for url in [
                'https://www.topcoder.com/tc?module=MatchList',
                'https://community.topcoder.com/longcontest/stats/?module=MatchList',
            ]:
                page = REQ.get(url)
                matches = re_round_overview.finditer(str(page))
                for match in matches:
                    date = datetime.strptime(match.group('date'), '%m.%d.%Y')
                    if abs(date - start_time) < timedelta(days=2):
                        title = match.group('title')
                        intersection = len(set(title.split()) & set(self.name.split()))
                        union = len(set(title.split()) | set(self.name.split()))
                        if intersection / union > 0.61803398875:
                            self.standings_url = urljoin(url, match.group('url'))
                            break
                if not self.standings_url:
                    break

        if not self.standings_url:
            raise InitModuleException('Not set standings url for %s' % self.name)

        url = self.standings_url + '&nr=100000042'
        page = REQ.get(url)
        result_urls = re.findall(r'<a[^>]*href="(?P<url>[^"]*)"[^>]*>Results</a>', str(page), re.I)

        if not result_urls:  # marathon match
            rows = etree.HTML(page).xpath("//table[contains(@class, 'stat')]//tr")
            header = None
            for row in rows:
                r = parsed_table.ParsedTableRow(row)
                if len(r.columns) < 8:
                    continue
                values = [c.value.strip().replace(u'\xa0', '') for c in r.columns]
                if header is None:
                    header = values
                    continue

                d = dict(list(zip(header, values)))
                handle = d.pop('Handle')
                d = self._dict_as_number(d)
                if 'rank' not in d:
                    continue
                row = result.setdefault(handle, {})
                row.update(d)

                score = row.pop('final_score' if 'final_score' in row else 'provisional_score')
                row['member'] = handle
                row['place'] = row.pop('rank')
                row['solving'] = int(round(score))
                row['solved'] = {'solving': 1 if score > 0 else 0}
                row['score'] = score
        else:  # single round match
            for result_url in result_urls:
                url = urljoin(self.standings_url, result_url + '&em=1000000042')
                url = url.replace('&amp;', '&')
                division = int(parse_qs(url)['dn'][0])
                page = REQ.get(url)
                rows = etree.HTML(page).xpath("//tr[@valign='middle']")
                header = None
                for row in rows:
                    r = parsed_table.ParsedTableRow(row)
                    if len(r.columns) < 10:
                        continue
                    values = [c.value for c in r.columns]
                    if header is None:
                        header = values
                        continue

                    d = dict(list(zip(header, values)))
                    handle = d.pop('Coders')
                    d = self._dict_as_number(d)
                    if 'division_placed' not in d:
                        continue
                    row = result.setdefault(handle, {})
                    row.update(d)

                    row['member'] = handle
                    row['place'] = row.pop('division_placed')
                    row['solving'] = int(round(row['point_total']))
                    row['score'] = row.pop('point_total')
                    row['solved'] = {'solving': 0}
                    row['division'] = 'I' * division
        standings = {
            'result': result,
            'url': self.standings_url,
        }
        return standings


if __name__ == "__main__":
    # statictic = Statistic(
    #     name='TCO19 SRM 752',
    #     standings_url='https://www.topcoder.com/stat?module=MatchList&nr=200&sr=1&c=round_overview&er=5&rd=17420',
    #     key='TCO19 SRM 752. 06.03.2019',
    # )
    # pprint(statictic.get_result('tourist'))
    # statictic = Statistic(
    #     name='TCO19 Algorithm Round 1B',
    #     standings_url='https://www.topcoder.com/stat?module=MatchList&nr=200&sr=1&c=round_overview&er=5&rd=17509',
    #     key='TCO19 Algorithm Round 1B. 01.05.2019',
    # )
    # pprint(statictic.get_result('aropan'))
    statictic = Statistic(
        name='TCO19 SRM 752',
        # standings_url='https://community.topcoder.com/longcontest/stats/?module=ViewOverview&rd=17427',
        standings_url=None,
        key='TCO19 SRM 752. 06.03.2019',
        start_time=datetime.strptime('06.03.2019', '%d.%m.%Y'),
    )
    from pprint import pprint
    pprint(statictic.get_standings())
