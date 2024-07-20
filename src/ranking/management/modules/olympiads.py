#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os
import re
from collections import OrderedDict
from datetime import timedelta
from functools import partial

import tqdm
import yaml
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from ranking.management.modules.common import DOT, REQ, SPACE, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings

logging.getLogger('geopy').setLevel(logging.INFO)


class Statistic(BaseModule):
    LOCATION_CACHE_FILE = os.path.join(os.path.dirname(__file__), '.locations.yaml')

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None, **kwargs):
        geolocator = Nominatim(user_agent="clist.by")
        geocode_func = partial(geolocator.geocode, timeout=10)
        geocode = RateLimiter(geocode_func, min_delay_seconds=1, max_retries=3)

        season = self.key.split('.')[0]

        if not self.standings_url:
            return {}

        page = REQ.get(self.standings_url)
        page = re.sub('<(/?)tl([^>]*)>', r'<\1tr\2>', page)

        regex = '<table[^>]*class="standings"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if not match:
            regex = r'<table\s*(?:align="center"\s*)?border\s*=\s*"?1"?\s*(?:align="center"\s*)?>.*?</table>'
            matches = re.finditer(regex, page, re.DOTALL)
            for match in matches:
                pass
        if not match:
            raise ExceptionParseStandings('not found standings table')
        html_table = match.group(0)
        c_mapping = {
            'place': 'place',
            'место': 'place',
            'user': 'name',
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

        locations = None
        if os.path.exists(self.LOCATION_CACHE_FILE):
            with open(self.LOCATION_CACHE_FILE, 'r') as fo:
                locations = yaml.safe_load(fo)
        if locations is None:
            locations = {}

        def get_location(loc_info):
            loc_info = re.sub(r'[.,\s]+', ' ', loc_info).strip().lower()
            if loc_info not in locations:
                try:
                    ru = geocode(loc_info, language='ru')
                    en = geocode(loc_info, language='en')
                    if ru is None and en is None:
                        locations[loc_info] = None
                    else:
                        locations[loc_info] = {'ru': ru.address, 'en': en.address}
                except Exception:
                    pass

            return locations.get(loc_info)

        def get_country(address):
            *_, country = map(str.strip, address['en'].split(','))
            if country.startswith('The '):
                country = country[4:]
            return country

        try:
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
                        problem_info = problems_info.setdefault(letter, {
                            'short': letter,
                            'full_score': 100,
                        })
                        if letter.lower() != k.lower():
                            problem_info['name'] = k
                        if 'title' in v.attrs:
                            problem_info['name'] = v.attrs['title']

                        if v.value != DOT and v.value:
                            p = problems.setdefault(letter, {})

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

                addition = (statistics or {}).get(row['member'], {})
                if addition:
                    country = addition.get('country')
                    if country:
                        row.setdefault('country', country)
                    if 'country' not in row:
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

                            address = get_location(loc)
                            if address:
                                country = get_country(address)
                                row['country'] = country
                                break

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
        finally:
            with open(self.LOCATION_CACHE_FILE, 'wb') as fo:
                yaml.dump(locations, fo, encoding='utf8', allow_unicode=True)

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
