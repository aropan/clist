# -*- coding: utf-8 -*-

import re
from collections import OrderedDict
from urllib.parse import urljoin

from clist.templatetags.extras import as_number, slug
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from utils.timetools import parse_datetime


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        standings_url = re.sub(r'/\blist\b', '/scores', self.url)

        page = REQ.get(self.url)

        has_en = re.search('<option selected>en</option>', page)
        has_fi = re.search('<option selected>fi</option>', page)

        if not has_en and has_fi:
            form = REQ.form()
            form_data = form.get('post', {})
            if 'stmt_lang' not in form_data:
                raise ExceptionParseStandings('Language is not set')
            page = REQ.submit_form({'stmt_lang': 'en'}, form=form)

        matches = re.finditer(r'<[^>]*class="task"[^>]*>\s*<b>(?P<short>[^<]*)</b>\s*<a[^>]*href="(?P<url>[^"]*)"[^>]*>(?P<name>[^<]*)</a>', page)  # noqa: E501
        problem_infos = dict()
        for match in matches:
            short = match.group('short').strip()
            name = match.group('name').strip()
            url = urljoin(self.url, match.group('url').strip())
            problem_infos[short] = {'short': short, 'name': name, 'url': url}

        page = REQ.get(standings_url)
        table_class = re.search('<table[^>]*class="(?P<class>scoreboard[^>]*)"[^>]*>', page)
        table_class = table_class.group('class').split()
        table_class.remove('scoreboard')
        if len(table_class) != 1:
            raise ExceptionParseStandings(f'Unknown table class = {table_class}')
        kind = table_class[0].lower()

        result = {}
        table = parsed_table.ParsedTable(html=page, xpath='.//table[contains(@class,"scoreboard")]//tr')
        season = self.get_season()
        for r in table:
            if kind == 'ioi':
                name_el = r.pop('name')
                href = name_el.column.node.xpath('.//a')[0].attrib['href']
                handle = re.findall(r'(\d+)', href)[-1]
                name = name_el.value
                solving_field = 'score'
            elif kind == 'icpc':
                name = r.pop('team')
                if isinstance(name, list):
                    name = ' '.join([x.value for x in name])
                    name = name.strip()
                handle = f'{name} {season}'
                solving_field = 'sol.'
            else:
                raise ExceptionParseStandings('Unknown standings type')

            row = result.setdefault(handle, OrderedDict())
            row['member'] = handle
            row['name'] = name
            row['place'] = r.pop('#').value
            row['solving'] = r.pop(solving_field).value

            if 'time' in r:
                row['time'] = r.pop('time').value

            problems = row.setdefault('problems', {})
            for k, v in r.items():
                if k not in problem_infos or not v.value:
                    continue
                value, *other = v.value.split()
                value = as_number(value, force=True)
                if value is None:
                    continue
                p = problems.setdefault(k, {})
                classes = v.column.node.attrib.get('class', '').split()
                href = v.column.node.xpath('.//a')[0].attrib['href']
                p['url'] = urljoin(standings_url, href)
                if 'solved-first' in classes:
                    classes.append('solved')
                    p['first_ac'] = value
                if kind == 'ioi':
                    p['result'] = value
                    if value < 100:
                        p['partial'] = True
                elif kind == 'icpc':
                    if 'solved' in classes:
                        p['result'] = '+'
                        if value > 1:
                            p['result'] += str(value - 1)
                    elif 'failed' in classes:
                        p['result'] = f'-{value}'
                    else:
                        raise ExceptionParseStandings(f'Unknown problem result class = {classes}')
                    if other:
                        time = as_number(other[0], force=True)
                        if time is not None:
                            p['time'] = time

        standings = {
            'url': standings_url,
            'kind': kind,
            'result': result,
            'problems': list(problem_infos.values()),
        }
        return standings

    @staticmethod
    def get_archive_problems(resource, limit, **kwargs):
        problem_time = parse_datetime('2015-01-01')
        problemset_url = 'https://cses.fi/problemset/'
        page = REQ.get(problemset_url)
        ret = []

        task_lists = re.finditer(r'<h2>(?P<name>[^<]*)</h2>\s*(?P<page><ul[^>]*>.*?</ul>)', page)
        for task_list in task_lists:
            list_name = task_list.group('name')
            list_page = task_list.group('page')

            matches = re.finditer('<a[^>]*href="(?P<url>[^"]*/task/[^"]*)"[^>]*>(?P<name>[^<]*)</a>\s*<span[^>]*>(?P<detail>[^<]*)</span>', list_page)  # noqa
            for match in matches:
                if len(ret) == limit:
                    break
                url = urljoin(problemset_url, match.group('url').strip())
                name = match.group('name').strip()
                key = re.findall(r'\d+', url)[-1]
                info = {'tags': [slug(list_name)]}
                problem = dict(url=url, key=key, name=name, time=problem_time, info=info)
                detail = match.group('detail').strip()
                detail = re.findall(r'\d+', detail)
                if len(detail) == 2:
                    n_accepted, n_total = map(int, detail)
                    problem['n_accepted'] = n_accepted
                    problem['n_total'] = n_total
                    if n_total:
                        info['success_rate'] = n_accepted / n_total
                ret.append(problem)

        return ret
