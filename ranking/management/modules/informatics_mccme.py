# -*- coding: utf-8 -*-

import re
from pprint import pprint

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import InitModuleException, ExceptionParseStandings


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = 'http://informatics.mccme.ru/mod/monitor/view.php?id={0.key}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        if not self.key:
            raise InitModuleException()

    def get_standings(self, users=None):
        standings_url = Statistic.STANDING_URL_FORMAT_.format(self)
        page = REQ.get(standings_url, time_out=12)

        result = {}
        header = None
        prob_pos = None

        for match in re.findall(r'<tr[^>]*>\n.*?<\/tr>', page, re.DOTALL):
            match = match.replace('&nbsp;', ' ')

            member = None
            fields = []

            tds = re.finditer(r'<td[^>]*>.*(?:<\/td>)?', match)
            for i, td in enumerate(tds):
                td = td.group()
                value = re.sub('<[^>]*>', '', td).strip()

                attrs = dict(m.group('key', 'value') for m in re.finditer('(?P<key>[a-z]*)="?(?P<value>[^">]*)', td))
                if 'href' in attrs:
                    match = re.search('/user/.*id=(?P<id>[0-9]+)', attrs['href'])
                    if match:
                        member = match.group('id')
                if not header and prob_pos is None and attrs.get('rowspan', None) != '2':
                    prob_pos = i
                # value = attrs.get('title', value)
                # if 'href' in attrs:
                #     match = re.search('solutions/(?P<member>[^/]*)/', attrs['href'])
                #     if match:
                #         member = match.group('member')
                #         problem_names.append(i)
                fields.append(value)

            if not header:
                header = fields
                continue

            if prob_pos:
                header = header[:prob_pos] + fields + header[prob_pos + 1:]
                prob_pos = 0
                continue

            if not member:
                raise ExceptionParseStandings('Not found member')

            row = dict(list(zip(header, fields)))

            r = result.setdefault(member, {})
            r['member'] = member
            r['place'] = row['Место']
            r['attempts'] = row['Попыток']
            r['solving'] = row['Всего']

            problems = r.setdefault('problems', {})
            for k, v in row.items():
                if v and re.match('^[A-Z]$', k):
                    problems[k] = {'result': v}
            if not problems:
                r.pop('problems')
        standings = {
            'result': result,
            'url': standings_url,
        }
        return standings


if __name__ == '__main__':
    pprint(Statistic(key='18947').get_standings())
    pass
