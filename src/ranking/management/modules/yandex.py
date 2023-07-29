# -*- coding: utf-8 -*-

import html
import os
import re
from collections import OrderedDict
from urllib.parse import urljoin

import tqdm

from clist.templatetags.extras import get_item
from my_oauth.models import Service
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    YANDEX_API_URL = 'https://api.contest.yandex.net/api/public/v2'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.standings_url:
            url = self.url
            url = re.sub('enter/?', '', url)
            url = re.sub(r'\?.*$', '', url)
            url = re.sub('/?$', '', url)
            self.standings_url = os.path.join(url, 'standings')

    def get_submission_infos(self, statistics, names):
        already_processed = set()
        submission_infos = {}
        if statistics:
            for statistic_row in statistics.values():
                name = statistic_row.get('name')
                problems = statistic_row.get('problems')
                if not name or not problems:
                    continue
                for short, problem in problems.items():
                    if not problem.get('_submission_infos'):
                        continue
                    row_problems = submission_infos.setdefault(name, {})
                    _submission_infos = problem['_submission_infos']
                    row_problems[short] = {'_submission_infos': _submission_infos}
                    for submission_info in _submission_infos:
                        already_processed.add(submission_info['run_id'])

        coder_pk = get_item(self.resource.info, 'statistics.competitive_hustle_coder_pk')
        if not coder_pk:
            return submission_infos

        ouath_service = Service.objects.get(name='competitive-hustle')
        oauth_token = ouath_service.token_set.filter(coder__pk=coder_pk).first()
        if not oauth_token:
            return submission_infos

        access_token = oauth_token.access_token['access_token']
        headers = {'Authorization': f'OAuth {access_token}'}

        page = 0
        size = 10000
        total = None
        submissions = []
        while total is None or page * size < total:
            page += 1
            url = f'{Statistic.YANDEX_API_URL}/contests/{self.key}/submissions?page={page}&pageSize={size}'
            try:
                data = REQ.get(url, headers=headers, return_json=True)
            except FailOnGetResponse as e:
                LOG.warning(f'Fail to get submission ids: {e}')
                break
            submissions.extend(data['submissions'])
            total = data['count']
        run_ids = {s['id'] for s in submissions if s['id'] not in already_processed and s['author'] in names}

        run_ids = list(run_ids)
        batch_size = 20
        n_page = (len(run_ids) - 1) // batch_size + 1
        for page in tqdm.tqdm(range(n_page), total=n_page, desc='fetch submissions'):
            offset = batch_size * page
            run_ids_query = '&'.join(f'runIds={run_id}' for run_id in run_ids[offset:offset + batch_size])
            url = f'{Statistic.YANDEX_API_URL}/contests/{self.key}/submissions/multiple?{run_ids_query}'
            try:
                submissions = REQ.get(url, headers=headers, return_json=True)
            except FailOnGetResponse as e:
                LOG.warning(f'Fail to get submission infos: {e}')
                break
            for submission in submissions:
                name = submission['participantInfo']['name']
                short = submission['problemAlias']

                problems = submission_infos.setdefault(name, {})
                problem = problems.setdefault(short, {})

                submission_info = {'ip': submission['ip'], 'run_id': submission['runId']}
                problem.setdefault('_submission_infos', []).append(submission_info)

        return submission_infos

    def get_standings(self, users=None, statistics=None):
        if not hasattr(self, 'season'):
            year = self.start_time.year - (0 if self.start_time.month > 8 else 1)
            season = f'{year}-{year + 1}'
        else:
            season = self.season

        result = {}
        problems_info = OrderedDict()

        if not re.search('/[0-9]+/', self.standings_url):
            return {}

        url = self.standings_url
        n_page = 1
        contest_ips = set()
        submission_infos = None
        while True:
            page = REQ.get(url)

            match = re.search(
                '<table[^>]*class="[^"]*standings[^>]*>.*?</table>',
                page,
                re.MULTILINE | re.DOTALL
            )
            if not match:
                raise ExceptionParseStandings('Not found table standings')

            html_table = match.group(0)
            unnamed_fields = self.info.get('standings', {}).get('unnamed_fields', [])
            table = parsed_table.ParsedTable(html_table, unnamed_fields=unnamed_fields)

            for r in table:
                row = {}
                problems = row.setdefault('problems', {})
                solved = 0
                has_solved = False
                for k, v in list(r.items()):
                    if 'table__cell_role_result' in v.attrs['class']:
                        letter = k.split(' ', 1)[0]
                        if letter == 'X':
                            continue

                        p = problems_info.setdefault(letter, {'short': letter})
                        names = v.header.node.xpath('.//span/@title')
                        if len(names) == 1:
                            name = html.unescape(names[0])
                            sample = re.search(r'\((?P<full>[0-9]+)\s*балл.{,3}\)$', name, re.I)
                            if sample:
                                st, _ = sample.span()
                                name = name[:st].strip()
                                p['full_score'] = int(sample.group('full'))
                            p['name'] = name

                        p = problems.setdefault(letter, {})
                        n = v.column.node
                        if n.xpath('img[contains(@class,"image_type_success")]'):
                            res = '+'
                            p['binary'] = True
                        elif n.xpath('img[contains(@class,"image_type_fail")]'):
                            res = '-'
                            p['binary'] = False
                        else:
                            if ' ' not in v.value and not v.value.startswith('?'):
                                problems.pop(letter)
                                continue
                            res = v.value.split(' ', 1)[0]
                            res = res.replace(',', '')
                        p['result'] = res
                        if ' ' in v.value:
                            p['time'] = v.value.split(' ', 1)[-1]
                        if 'table__cell_firstSolved_true' in v.attrs['class']:
                            p['first_ac'] = True

                        if '+' in res or res.startswith('100'):
                            solved += 1

                        try:
                            has_solved = has_solved or '+' not in res and float(res) > 0
                        except ValueError:
                            pass
                    elif 'table__cell_role_participant' in v.attrs['class']:
                        title = v.column.node.xpath('.//@title')
                        if title:
                            name = str(title[0])
                        else:
                            name = v.value.replace(' ', '', 1)
                        row['name'] = name
                        row['member'] = name if ' ' not in name else f'{name} {season}'

                        country = v.column.node.xpath(".//div[contains(@class,'country-flag')]/@title")
                        if country:
                            row['country'] = str(country[0])

                    elif 'table__cell_role_place' in v.attrs['class']:
                        row['place'] = v.value
                    elif 'table__header_type_penalty' in v.attrs['class']:
                        row['penalty'] = int(v.value) if re.match('^-?[0-9]+$', v.value) else v.value
                    elif 'table__header_type_score' in v.attrs['class']:
                        row['solving'] = float(v.value.replace(',', ''))
                if has_solved:
                    row['solved'] = {'solving': solved}
                if not problems:
                    continue
                result[row['member']] = row

            n_page += 1
            match = re.search(f'<a[^>]*href="(?P<href>[^"]*standings[^"]*p[^"]*={n_page})"[^>]*>', page)
            if not match:
                break
            url = urljoin(url, match.group('href'))

        names = {row['name'] for row in result.values()}
        submission_infos = self.get_submission_infos(statistics, names) or {}

        for row in result.values():
            name = row['name']
            if name not in submission_infos:
                continue
            problems = row['problems']
            ips = set()
            for short, problem_data in submission_infos[name].items():
                problems.setdefault(short, {}).update(problem_data)
                ips |= {info['ip'] for info in problem_data.get('_submission_infos', [])}
            contest_ips |= ips
            row['_ips'] = list(sorted(ips))

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
        }

        if contest_ips:
            standings.setdefault('info_fields', []).append('_ips')
            standings['_ips'] = list(sorted(contest_ips))
        return standings
