# -*- coding: utf-8 -*-

import html
import os
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from datetime import timedelta
from urllib.parse import urljoin

import tqdm
from django.utils import timezone
from ipwhois import IPWhois
from ratelimiter import RateLimiter

from clist.templatetags.extras import as_number, get_item
from my_oauth.models import Service
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.common.locator import Locator
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    YANDEX_API_URL = 'https://api.contest.yandex.net/api/public/v2'
    SUBMISSION_FIELDS_MAPPING = {
        'submission_id': 'runId',
        'verdict_full': 'verdict',
        'verdict': lambda submission: ''.join(filter(str.isupper, submission['verdict'])),
        'max_memory_usage': 'maxMemoryUsage',
        'max_time_usage': 'maxTimeUsage',
        'time_in_seconds': lambda submission: submission['timeFromStart'] / 1000,
        'language': 'compiler',
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.standings_url:
            url = self.url
            url = re.sub('enter/?', '', url)
            url = re.sub(r'\?.*$', '', url)
            url = re.sub('/?$', '', url)
            self.standings_url = os.path.join(url, 'standings')

    def get_submission_infos(self, statistics, names_result):
        already_processed = set()
        submission_infos = {}
        max_run_id = self.contest.variables.get('max_run_id')
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
                    if max_run_id:
                        _submission_infos = [info for info in _submission_infos if info['run_id'] <= max_run_id]
                    row_problems[short] = {'_submission_infos': _submission_infos}
                    for submission_info in _submission_infos:
                        already_processed.add(submission_info['run_id'])

        coder_pk = get_item(self.resource.info, 'statistics.competitive_hustle_coder_pk')
        if not coder_pk:
            return submission_infos, None

        ouath_service = Service.objects.get(name='yandex-contest')
        oauth_token = ouath_service.token_set.filter(coder__pk=coder_pk).first()
        if not oauth_token:
            return submission_infos, None

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
        run_ids = [s['id'] for s in submissions if s['author'] in names_result]
        run_ids = [run_id for run_id in run_ids if run_id not in already_processed]
        if max_run_id:
            run_ids = [run_id for run_id in run_ids if run_id <= max_run_id]

        stop_fetch_submissions = False
        finish_time = timezone.now() + timedelta(minutes=10)
        rate_limiter = RateLimiter(max_calls=4, period=1)

        def fetch_submissions(page):
            nonlocal stop_fetch_submissions
            if stop_fetch_submissions:
                return
            if timezone.now() > finish_time:
                LOG.warning('Fetch submissions timeout')
                stop_fetch_submissions = True
                return
            with rate_limiter:
                offset = batch_size * page
                run_ids_query = '&'.join(f'runIds={run_id}' for run_id in run_ids[offset:offset + batch_size])
                url = f'{Statistic.YANDEX_API_URL}/contests/{self.key}/submissions/multiple?{run_ids_query}'
                try:
                    submissions = REQ.get(url, headers=headers, return_json=True)
                    return submissions
                except FailOnGetResponse as e:
                    LOG.warning(f'Fail to get submission infos: {e}')
                    stop_fetch_submissions = True

        run_ids = list(set(run_ids))
        batch_size = 50
        n_page = (len(run_ids) - 1) // batch_size + 1
        n_processed = len(already_processed)
        n_total = len(run_ids) + n_processed
        with PoolExecutor(max_workers=8) as executor, tqdm.tqdm(total=n_page, desc='fetch submissions') as pbar:
            for submissions in executor.map(fetch_submissions, range(n_page)):
                pbar.update()
                if submissions is None:
                    continue
                for submission in submissions:
                    n_processed += 1
                    name = submission['participantInfo']['name']
                    short = submission['problemAlias']
                    final_score = submission.get('finalScore')
                    submission_problem = submission_infos.setdefault(name, {}).setdefault(short, {})
                    problem = get_item(names_result[name], ('problems', short))
                    if (
                        not problem or
                        as_number(final_score) == as_number(problem.get('result')) and
                        ('submission_id' not in problem or submission['runId'] < problem['submission_id'])
                    ):
                        fields_data = problem or submission_problem
                        for field, source in Statistic.SUBMISSION_FIELDS_MAPPING.items():
                            if callable(source):
                                value = source(submission)
                            else:
                                value = submission[source]
                            fields_data[field] = value

                    submission_info = {'ip': submission['ip'], 'run_id': submission['runId']}
                    submission_problem.setdefault('_submission_infos', []).append(submission_info)

        submissions_percentage = 100 * n_processed // n_total if n_total else False
        return submission_infos, submissions_percentage

    def get_standings(self, users=None, statistics=None, **kwargs):
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
        tqdm_pagination = None
        n_page = 1
        submission_infos = None
        while True:
            page = REQ.get(url)

            if n_page == 1:
                pages = re.findall('<a[^>]*href="[^"]*standings[^"]*p[^"]*=([0-9]+)"[^>]*>', page)
                if pages:
                    max_page = max(map(int, pages))
                    tqdm_pagination = tqdm.tqdm(total=max_page, desc='fetch standings pages')

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

                statistics_problems = get_item(statistics, (row['member'], 'problems'), {})
                for short, problem in problems.items():
                    if short not in statistics_problems:
                        continue
                    statistics_problem = statistics_problems[short]
                    for key, value in statistics_problem.items():
                        if key in Statistic.SUBMISSION_FIELDS_MAPPING and key not in problem:
                            problem[key] = value

                result[row['member']] = row
            if tqdm_pagination:
                tqdm_pagination.update()
            n_page += 1
            match = re.search(f'<a[^>]*href="(?P<href>[^"]*standings[^"]*p[^"]*={n_page})"[^>]*>', page)
            if not match:
                break
            url = urljoin(url, match.group('href'))
        if tqdm_pagination:
            tqdm_pagination.close()

        hidden_fields = set(Locator.location_fields)
        default_locations = get_item(self.resource, 'info.standings.default_locations')
        with Locator(default_locations=default_locations) as locator:
            for row in tqdm.tqdm(result.values(), desc='fetch locations'):
                if 'country' in row:
                    continue
                name = row['name']
                match = re.search(r',\s*(?P<address>[^,]+)$', name)
                if not match:
                    continue
                address = match.group('address')
                location = locator.get_location_dict(address, lang='ru')
                if not location:
                    continue
                row.update(location)

        names_result = {row['name']: row for row in result.values()}
        submission_infos, submissions_percentage = self.get_submission_infos(statistics, names_result) or {}
        whois = self.info.setdefault('_whois', {})
        contest_ips = set()
        contest_n_ips = set()
        contest_whois = defaultdict(set)

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
            contest_n_ips |= {len(ips)}
            row['_n_ips'] = len(ips)

            for ip in row['_ips']:
                if ip not in whois:
                    lookup = IPWhois(ip).lookup_whois()
                    nets = lookup.get('nets')
                    if not nets:
                        continue
                    net = nets[0]
                    description = net.get('description')
                    if description:
                        description = re.sub(r'\n\s*', '; ', description)
                    whois[ip] = {
                        'name': net.get('name'),
                        'range': net.get('range'),
                        'description': description,
                        'country': net.get('country'),
                    }
                for field, value in whois[ip].items():
                    if value:
                        key = f'_whois_{field}'
                        row_values = row.setdefault(key, [])
                        row_values.append(value)
                        contest_whois[key].add(value)

        standings = {
            'result': result,
            'url': self.standings_url,
            'problems': list(problems_info.values()),
            'hidden_fields': list(hidden_fields),
            'parsed_percentage': submissions_percentage,
        }

        if contest_ips:
            info_fields = standings.setdefault('info_fields', [])
            info_fields.extend(['_ips', '_n_ips', '_whois'])
            standings['_ips'] = list(sorted(contest_ips))
            standings['_n_ips'] = list(sorted(contest_n_ips))
            standings['_whois'] = whois
            for field, values in contest_whois.items():
                info_fields.append(field)
                standings[field] = list(sorted(values))

        now = timezone.now()
        if now < self.end_time < now + timedelta(hours=2):
            if submissions_percentage and submissions_percentage < 100:
                standings['timing_statistic_delta'] = timedelta(minutes=1)

        return standings
