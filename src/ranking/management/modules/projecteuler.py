#!/usr/bin/env python

import io
import json
import os
import random
import re
from collections import OrderedDict
from datetime import timedelta
from pprint import pprint

import pytesseract
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from first import first
from PIL import Image

from ranking.management.modules import conf
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            self.standings_url = f'https://projecteuler.net/fastest={self.key}'

        user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36'  # noqa

        def get_standings_page(req):
            page = req.get(self.standings_url, headers={'User-Agent': user_agent})

            unauthorized = not re.search('<form[^>]*action="sign_out"[^>]*>', page)
            if unauthorized:
                for attempt in range(20):
                    while True:
                        value = f'{random.random():.16f}'
                        image_bytes = req.get(f'https://projecteuler.net/captcha/show_captcha.php?{value}')
                        image_stream = io.BytesIO(image_bytes)
                        image_rgb = Image.open(image_stream)
                        text = pytesseract.image_to_string(image_rgb, config='--oem 0 --psm 13 digits')
                        text = text.strip()
                        if re.match('^[0-9]{5}$', text):
                            break

                    req.get('https://projecteuler.net/sign_in')
                    page = req.submit_form(
                        name='sign_in_form',
                        action=None,
                        data={
                            'username': conf.PROJECTEULER_USERNAME,
                            'password': conf.PROJECTEULER_PASSWORD,
                            'captcha': text,
                            'remember_me': '1',
                        },
                    )
                    match = re.search('<p[^>]*class="warning"[^>]*>(?P<message>[^<]*)</p>', page)
                    if match:
                        req.print(match.group('message'))
                    else:
                        break
                else:
                    raise ExceptionParseStandings('Did not recognize captcha for sign in')
                page = req.get(self.standings_url)

            return page

        with REQ.with_proxy(
            time_limit=5,
            n_limit=100,
            filepath_proxies=os.path.join(os.path.dirname(__file__), '.projecteuler.proxies'),
            connect=get_standings_page,
        ) as req:
            page = req.proxer.get_connect_ret()
            if req.proxer.proxy:
                with open('logs/legacy/projecteuler.proxy', 'w') as fo:
                    json.dump(req.proxer.proxy, fo, indent=2)

        result = {}

        problem_key = self.key
        problem_info = {
            'code': problem_key,
            'url': self.url,
            'n_total': 100,
        }
        if '. ' in self.name:
            problem_info['name'] = self.name.split('. ', 1)[1].strip()
        problems_info = [problem_info]

        regex = '<table[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL)

        if html_table:
            table = parsed_table.ParsedTable(html_table.group(0))
            for r in table:
                row = OrderedDict()
                row['solving'] = 1

                problems = row.setdefault('problems', {})
                problem = problems.setdefault(problem_key, {})
                problem['result'] = '+'
                problem['binary'] = True

                for k, v in r.items():
                    if isinstance(v, list):
                        place, country = v
                        row['place'] = re.match('[0-9]+', place.value).group(0)
                        country = first(country.column.node.xpath('.//@title'))
                        if country:
                            row['country'] = str(country)
                    elif k == 'Time To Solve':
                        params = {}
                        for x in v.value.split(', '):
                            value, field = x.split()
                            if field[-1] != 's':
                                field += 's'
                            params[field] = int(value)
                        rel_delta = relativedelta(**params)
                        now = timezone.now()
                        delta = now - (now - rel_delta)
                        row['penalty'] = problem['time_in_seconds'] = int(delta.total_seconds())
                    elif k == 'User':
                        member = first(v.column.node.xpath('.//@title')) or v.value
                        row['member'] = member
                    else:
                        row[k.lower()] = v.value
                if 'member' not in row:
                    continue
                result[row['member']] = row

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': problems_info,
            'fields_types': {'penalty': ['timedelta']},
        }

        if len(result) < 100 and 'No data available' not in page:
            delta = timezone.now() - self.start_time
            if delta < timedelta(days=1):
                standings['timing_statistic_delta'] = timedelta(minutes=60)
            elif delta < timedelta(days=30):
                standings['timing_statistic_delta'] = timedelta(days=1)
            elif delta < timedelta(days=365):
                standings['timing_statistic_delta'] = timedelta(days=7)
            else:
                standings['timing_statistic_delta'] = timedelta(days=30)

        return standings


if __name__ == "__main__":
    statictic = Statistic(url='https://projecteuler.net/problem=689', key='689', standings_url=None)
    pprint(statictic.get_result('theshuffler', 'Tepsi', 'jpeg13'))
