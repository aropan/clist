# -*- coding: utf-8 -*-

import re
from collections import OrderedDict, defaultdict
from datetime import timedelta
from pprint import pprint  # noqa
from urllib.parse import urljoin

from ranking.management.modules.common import REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException


class Statistic(BaseModule):

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

        if not self.name or not self.start_time or not self.url:
            raise InitModuleException()

    def get_standings(self, users=None, statistics=None):
        standings_data = None
        if not self.standings_url:
            page = REQ.get(urljoin(self.url, '/'))

            for name in (
                'Соревнования',
                'Тренировочные олимпиады',
            ):
                match = re.search('<a[^>]*href="(?P<url>[^"]*)"[^>]*>{}<'.format(name), page)
                url = match.group('url')
                page = REQ.get(url)

            regex = '''
            <a[^>]*href=["']?[^<"']*cid=(?P<cid>[0-9]+)[^>]*>[^>]*{}[^>]*</a>.*?
            <a[^>]*href="(?P<url>[^"]*)"[^>]*>{}<
            '''.format(
                re.escape(self.name),
                re.escape('Результаты прошедших тренировок'),
            )
            match = re.search(regex, page, re.DOTALL | re.IGNORECASE | re.VERBOSE)

            if not match:
                raise ExceptionParseStandings('Not found standings urls list')

            url = match.group('url')
            cid = match.group('cid')
            last_standings_data = self.resource.info['parse']['last_standings_data'].get(cid, {})
            page = REQ.get(url)

            dates = [self.start_time, self.start_time - timedelta(days=1)]
            dates = [d.strftime('%Y-%m-%d') for d in dates]
            re_dates = '|'.join(dates)

            regex = r'''
            <tr[^>]*>[^<]*<td[^>]*>\s*(?P<date>{})\s*</td>[^<]*
            <td[^>]*>(?P<title>[^<]*)</td>[^<]*
            <td[^>]*>[^<]*<a[^>]*href\s*=["\s]*(?P<url>[^">]*)["\s]*[^>]*>
            '''.format(re_dates)
            matches = re.findall(regex, page, re.MULTILINE | re.VERBOSE)

            datas = [
                {'date': date.strip(), 'title': title.strip(), 'url': urljoin(url, u)}
                for date, title, u in matches
            ]
            if len(datas) > 1:
                regex = r'[0-9]\s*-\s*[0-9].*(?:[0-9]\s*-\s*[0-9].*\bкл\b|школа)'
                datas = [d for d in datas if not re.search(regex, d['title'], re.I)]

            if last_standings_data:
                datas = [d for d in datas if d['date'] > last_standings_data['date']]

            if not datas:
                raise ExceptionParseStandings('Not found standings url')

            if len(datas) > 1:
                _datas = [d for d in datas if d['date'] == dates[0]]
                if _datas:
                    datas = _datas

            if len(datas) > 1:
                ok = True
                urls_map = {}
                for d in datas:
                    url = d['url']
                    page = REQ.get(url)
                    path = re.findall('<td[^>]*nowrap><a[^>]*href="(?P<href>[^"]*)"', page)
                    if len(path) < 2:
                        ok = False
                    parent = urljoin(url, path[-2])
                    urls_map.setdefault(parent, d)
                if len(urls_map) > 1:
                    standings_data = datas[0]
                elif not ok:
                    raise ExceptionParseStandings('Too much standing url')
                else:
                    standings_data = list(urls_map.values())[0]
            else:
                standings_data = datas[0]

            page = REQ.get(standings_data['url'])
            self.standings_url = REQ.last_url

        try:
            page = REQ.get(self.standings_url)
        except FailOnGetResponse as e:
            if e.code == 404:
                raise ExceptionParseStandings('Not found response from standings url')
            raise e

        def get_table(page):
            html_table = re.search('<table[^>]*bgcolor="silver"[^>]*>.*?</table>',
                                   page,
                                   re.MULTILINE | re.DOTALL).group(0)
            table = parsed_table.ParsedTable(html_table, as_list=True)
            return table

        table = get_table(page)

        problems_info = OrderedDict()
        max_score = defaultdict(float)

        scoring = False
        is_olymp = False

        def get_uid(v):
            nonlocal is_olymp
            hrefs = v.column.node.xpath('a/@href')
            if not hrefs:
                return
            href = hrefs[0]
            match = re.search(r'olympResultsShowUserRank.*u\.id=(?P<uid>[0-9]+)', href)
            if match:
                is_olymp = True
                return 'olymp' + match.group('uid')
            match = re.search('[0-9]+$', href)
            return match.group(0)

        def is_problem(v):
            hrefs = v.header.node.xpath('a/@href')
            return any('sortid' not in href.lower() for href in hrefs)

        result = {}
        for r in table:
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            pid = 0
            solving = 0
            for k, v in r:
                if k == 'Имя':
                    uid = get_uid(v)
                    if uid is None:
                        continue
                    row['member'] = uid
                    row['name'] = v.column.node.xpath('a/text()')[0]
                    if uid.startswith('olymp'):
                        info = row.setdefault('info', {})
                        info['_no_profile_url'] = True
                elif k == 'Место':
                    row['place'] = v.value
                elif k == 'Время':
                    row['penalty'] = int(v.value)
                elif k in ['Сумма', 'Задачи']:
                    if v.value:
                        row['solving'] = float(v.value)
                elif k == 'Область':
                    row['region'] = v.value
                elif k == 'Класс':
                    match = re.search('^[0-9]+', v.value)
                    row['class'] = int(match.group(0)) if match else v.value
                elif is_problem(v):
                    if is_olymp:
                        pid += 1
                        k = str(pid)
                    problems_info[k] = {'short': k}
                    if v.value:
                        p = problems.setdefault(k, {})
                        p['result'] = v.value

                        if v.value and v.value[0] not in ['-', '+']:
                            scoring = True
                            solving += float(v.value)

                        try:
                            max_score[k] = max(max_score[k], float(v.value))
                        except ValueError:
                            pass
                elif k:
                    row[k.strip()] = v.value.strip()
                elif v.value.strip().lower() == 'log':
                    href = v.column.node.xpath('.//a/@href')
                    if href:
                        row['url'] = urljoin(self.standings_url, href[0])

            if 'solving' not in row:
                row['solving'] = solving
                row.pop('place', None)

            diploma = row.pop('Диплом', None)
            if diploma:
                match = re.search(r'(?P<diploma>[0-9]+)\s+ст', diploma)
                if match:
                    diploma = int(match.group('diploma'))
                    row.update({
                        "medal": ["gold", "silver", "bronze"][diploma - 1],
                        "_diploma": "I" * diploma,
                        "_medal_title_field": "_diploma",
                    })
                elif diploma.lower().replace(' ', '') == 'п.о.':
                    row.update({
                        "medal": "honorable",
                        "_honorable": "mention",
                        "_medal_title_field": "_honorable"
                    })
            if 'member' not in row:
                continue
            result[row['member']] = row

        last_solving = None
        last_rank = None
        ordered_results = sorted(result.values(), key=lambda r: (-r['solving'], r.get('penalty', 0)))
        for rank, row in enumerate(ordered_results, start=1):
            solving = row['solving']
            if last_solving is None or abs(solving - last_solving) > 1e-6:
                last_solving = solving
                last_rank = rank
            if 'place' not in row:
                row['place'] = last_rank

        if scoring and not is_olymp:
            match = re.search(r'<b[^>]*>\s*<a[^>]*href="(?P<url>[^"]*)"[^>]*>ACM</a>\s*</b>', page)
            if match:
                page = REQ.get(match.group('url'))
                table = get_table(page)
                for r in table:
                    uid = None
                    for k, v in r:
                        if k == 'Имя':
                            uid = get_uid(v)
                            if uid is None:
                                continue
                        elif is_problem(v) and uid and v.value:
                            if v.value[0] == '-':
                                result[uid]['problems'][k]['partial'] = True
                            elif v.value[0] == '+':
                                result[uid]['problems'][k]['partial'] = False
                                problems_info[k]['full_score'] = result[uid]['problems'][k]['result']

        for r in result.values():
            solved = 0
            for k, p in r['problems'].items():
                if p.get('partial'):
                    continue
                score = p['result']
                if score.startswith('+') or 'partial' in p and not p['partial']:
                    solved += 1
                else:
                    try:
                        score = float(score)
                    except ValueError:
                        continue
                    if abs(max_score[k] - score) < 1e-9 and score > 0:
                        solved += 1
            r['solved'] = {'solving': solved}

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'info_fields': ['_standings_data'],
        }

        if self.info.get('series'):
            standings['series'] = self.info['series']

        if result and standings_data:
            standings['_standings_data'] = standings_data
            self.resource.info['parse']['last_standings_data'][cid] = standings_data
            self.resource.save()

        return standings


if __name__ == '__main__':
    import os
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'pyclist.settings'

    from django import setup
    setup()

    from django.utils import timezone

    from clist.models import Contest

    qs = Contest.objects \
        .filter(host='dl.gsu.by', end_time__lt=timezone.now()) \
        .order_by('-start_time')
    for contest in qs[:1]:
        contest.standings_url = None

        statistic = Statistic(
            name=contest.title,
            url=contest.url,
            key=contest.key,
            standings_url=contest.standings_url,
            start_time=contest.start_time,
        )

        try:
            pprint(statistic.get_standings())
        except Exception:
            pass
