#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import re
from collections import OrderedDict
from datetime import timedelta

import tqdm

from ranking.management.modules.common import DOT, REQ, SPACE, BaseModule, parsed_table
from ranking.management.modules.common.locator import Locator
from ranking.management.modules.excepts import ExceptionParseStandings

logging.getLogger('geopy').setLevel(logging.INFO)


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        season = self.key.split('.')[0]

        if not self.standings_url:
            return {}

        page = REQ.get(self.standings_url)
        page = re.sub('<(/?)tl([^>]*)>', r'<\1tr\2>', page)

        for regex in [
            '<table[^>]*class="standings"[^>]*>.*?</table>',
            r'<table\s*(?:align="center"\s*)?border\s*=\s*"?1"?\s*(?:align="center"\s*)?>.*?</table>',
            r'<table\s*class="table\s*table-striped">.*?</table>',
        ]:
            matches = re.findall(regex, page, re.DOTALL)
            if matches:
                html_table = matches[-1]
                break
        else:
            raise ExceptionParseStandings('not found standings table')

        c_mapping = {
            'place': 'place',
            'место': 'place',
            'user': 'name',
            'фио': 'name',
            'team': 'name',
            'участник': 'name',
            'solved': 'solved',
            'total': 'solved',
            'имя': 'first_name',
            'фамилия': 'last_name',
            'отчество': 'middle_name',
            'логин': 'login',
            'login': 'login',
            'класс': 'class',
            'город': 'city',
            'субъект российской федерации (для иностранных участников - государство)': 'city',
            'балл': 'solving',
            'сумма': 'solving',
            'баллы': 'solving',
            'score': 'solving',
            'sum': 'solving',
            'итог': 'solving',
            'диплом': 'diploma',
            'степень диплома': 'diploma',
            'номер диплома': 'diploma_number',
            'страна': 'country',
            'школа (сокр.)': 'school',
            'школа': 'school',
            'учебное зачедение, класс': 'school',
            'регион/статус': 'region',
            'регион': 'region',
            'имя в таблице': 'handle',
            'uid': 'uid',
        }

        table = parsed_table.ParsedTable(html_table, strip_empty_columns=True)

        result = {}
        problems_info = OrderedDict()
        has_bold = False
        last, place, placing = None, None, {}
        for idx, r in enumerate(tqdm.tqdm(table, total=len(table)), start=1):
            row = OrderedDict()
            problems = row.setdefault('problems', {})
            letter = chr(ord('A') - 1)
            solved = 0
            for k, v in list(r.items()):
                is_russian = bool(re.search('[а-яА-Я]', k))
                c = v.attrs.get('class')
                c = c.split()[0] if c else k.lower()
                if c and c.startswith('st_'):
                    c = c[3:].lower()
                if c in ['prob'] or c not in c_mapping and not is_russian:
                    letter = chr(ord(letter) + 1)
                    short = k if re.match('^[A-Z][0-9]+$', k) else letter
                    problem_info = problems_info.setdefault(short, {
                        'short': short,
                        'full_score': 100,
                    })
                    if short.lower() != k.lower():
                        problem_info['name'] = k
                    if 'title' in v.attrs:
                        problem_info['name'] = v.attrs['title']

                    if v.value != DOT and v.value:
                        p = problems.setdefault(short, {})

                        if v.column.node.xpath('b'):
                            p['partial'] = False
                            has_bold = True

                        v = v.value
                        if SPACE in v:
                            v, t = v.split(SPACE, 1)
                            t = t.strip()
                            m = re.match(r'^\((?P<val>[0-9]+)\)$', t)
                            if m:
                                t = int(m.group('val'))
                                if t > 1:
                                    p['attempts'] = t - 1
                            else:
                                p['time'] = t

                        try:
                            score = float(v)
                            p['result'] = v
                            p['partial'] = score < problem_info['full_score']
                        except ValueError:
                            pass
                        if 'partial' in p and not p['partial']:
                            solved += 1
                else:
                    v = v.value.strip()
                    if not v or v == '-':
                        continue
                    c = c_mapping.get(c, c).lower()
                    row[c] = v

                    if c == 'diploma':
                        row['_medal_title_field'] = 'diploma'
                        v = v.lower().split()[0]
                        if re.search('(^в.к|^вне)', v):
                            continue
                        if v in ['gold', 'i', '1'] or v.startswith('перв'):
                            row['medal'] = 'gold'
                        elif v in ['silver', 'ii', '2'] or v.startswith('втор'):
                            row['medal'] = 'silver'
                        elif v in ['bronze', 'iii', '3'] or v.startswith('трет'):
                            row['medal'] = 'bronze'
                        else:
                            row['medal'] = 'honorable'

            if 'solving' not in row:
                if 'solved' in row:
                    row['solving'] = row.pop('solved')
                else:
                    continue
            row['solved'] = {'solving': solved}

            if 'place' not in row:
                if place is None and idx != 1:
                    continue
                if row['solving'] != last:
                    place = idx
                    last = row['solving']
                placing[place] = idx
                row['place'] = place

            if 'name' not in row:
                if 'first_name' in row and 'last_name' in row:
                    row['name'] = row['last_name'] + ' ' + row['first_name']
                elif 'first_name' in row and 'last_name' not in row:
                    row['name'] = row.pop('first_name')

            if 'login' in row:
                row['member'] = row['login']
                if 'name' in row:
                    row['_name_instead_key'] = True
            elif 'name' in row:
                name = row['name']
                if ' ' in name:
                    row['member'] = name + ' ' + season
                else:
                    row.pop('name')
                    row['member'] = name
            else:
                row['member'] = f'{self.pk}-{idx}'
            result[row['member']] = row

        if placing:
            for row in result.values():
                place = row['place']
                last = placing[place]
                row['place'] = str(place) if place == last else f'{place}-{last}'

        if has_bold:
            for row in result.values():
                for p in row.get('problems').values():
                    if 'partial' not in p and 'result' in p:
                        p['partial'] = True

        with Locator() as locator:
            for row in result.values():
                addition = (statistics or {}).get(row['member'], {})
                if not addition:
                    continue
                country = addition.get('country')
                if country:
                    row.setdefault('country', country)
                if 'country' in row:
                    continue

                locs = []
                if 'city' in row:
                    locs.append(row['city'])
                if 'extra' in row:
                    extra = row['extra']
                    extra = re.sub(r'\s*(Не\s*РФ|Not\s*RF|Участник\s*вне\s*конкурса):\s*',
                                   ' ', extra, re.IGNORECASE)
                    extra = re.sub('<[^>]*>', '', extra)
                    locs.extend(re.split('[,:]', extra))
                for loc in locs:
                    loc = re.sub(r'\s*[0-9]+\s*', ' ', loc)
                    loc = loc.strip()

                    country = locator.get_country(loc)
                    if country:
                        row['country'] = country
                        break

        standings = {
            'result': result,
            'problems': list(problems_info.values()),
            'hidden_fields': [
                'extra',
                'first_name',
                'last_name',
                'middle_name',
                'class',
                'city',
                'country',
                'diploma',
                'school',
                'login',
                'region',
                'uid',
                'handle',
                'diploma_number',
            ],
        }
        if not statistics and result:
            standings['timing_statistic_delta'] = timedelta(minutes=5)

        return standings
