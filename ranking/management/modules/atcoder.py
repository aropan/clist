# -*- coding: utf-8 -*-

import collections
import json
import re
import urllib.parse
import html
import functools
from copy import deepcopy
from pprint import pprint
from datetime import timedelta, datetime
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import pytz
import arrow
from first import first
from tqdm import tqdm

from ranking.management.modules.common import REQ, FailOnGetResponse, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.management.modules import conf


class Statistic(BaseModule):
    STANDING_URL_ = '{0.url}/standings'
    RESULTS_URL_ = '{0.url}/results'
    SUBMISSIONS_URL_ = '{0.url}/submissions'
    PROBLEM_URL_ = '{0.url}/tasks/{1}_{2}'
    HISTORY_URL_ = '{0.scheme}://{0.netloc}/users/{1}/history'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self.cid = self.key
        self._username = conf.ATCODER_HANDLE
        self._password = conf.ATCODER_PASSWORD
        self._stop = None

    def _get(self, *args, **kwargs):
        page = REQ.get(*args, **kwargs)
        form = REQ.form(limit=2, selectors=['class="form-horizontal"'])
        if form:
            form['post'].update({
                'username': self._username,
                'password': self._password,
            })
            page = REQ.get(form['url'], post=form['post'])
        return page

    def fetch_submissions(self, fuser=None, page=1):
        url = self.SUBMISSIONS_URL_.format(self) + f'?page={page}'
        if fuser:
            url += f'&f.User={fuser}'

        for _ in range(4):
            if self._stop:
                return

            try:
                page = REQ.get(url)
                break
            except FailOnGetResponse:
                pass
        else:
            return None, None, None, None

        regex = '<table[^>]*>.*?</table>'
        html_table = re.search(regex, page, re.DOTALL).group(0)
        table = parsed_table.ParsedTable(html_table)

        pages = re.findall(r'''<a[^>]*href=["'][^"']*/submissions\?[^"']*page=([0-9]+)[^"']*["'][^>]*>[0-9]+</a>''', page)  # noqa
        n_page = max(map(int, pages))

        return url, page, table, n_page

    def _update_submissions(self, fusers, standings):
        result = standings['result']

        with PoolExecutor(max_workers=8) as executor:
            submissions = list(tqdm(executor.map(self.fetch_submissions, fusers),
                                    total=len(fusers),
                                    desc='gettings first page'))

            for fuser, (url, page, table, n_page) in zip(fusers, submissions):
                if url is None:
                    continue

                submissions_times = {}

                def process_page(url, page, table):
                    last_submission_time = 0
                    for r in table:
                        row = dict()
                        for k, v in list(r.items()):
                            if v.value == 'Detail':
                                href = first(v.column.node.xpath('.//a/@href'))
                                if href:
                                    row['url'] = urllib.parse.urljoin(url, href)
                                    row['external_solution'] = True
                            else:
                                k = k.lower().replace(' ', '_')
                                row[k] = v.value

                        submission_time = arrow.get(row['submission_time'])
                        upsolve = submission_time >= self.end_time
                        row['submission_time'] = submission_time.timestamp
                        last_submission_time = max(last_submission_time, row['submission_time'])

                        row['verdict'] = row.pop('status')
                        user = row.pop('user')
                        task = row.pop('task').split()[0]
                        score = row.pop('score')

                        res = result.setdefault(user, collections.OrderedDict())
                        res.setdefault('member', user)
                        problems = res.setdefault('problems', {})
                        problem = problems.setdefault(task, {})
                        if upsolve:
                            problem = problem.setdefault('upsolving', {})

                            st = submissions_times.setdefault((user, task), problem.get('submission_time'))
                            if float(score) > 0:
                                row['result'] = score
                            elif not float(problem.get('result', 0)) > 0:
                                if (
                                    (not st or st < row['submission_time'])
                                    and row['submission_time'] != problem.get('submission_time')
                                ):
                                    row['result'] = str(int(problem.get('result', 0)) - 1)

                        if 'submission_time' in problem and row['submission_time'] < problem['submission_time']:
                            continue
                        problem.update(row)
                    return last_submission_time

                st_data = result.get(fuser, {}) if fuser else standings
                limit_st = st_data.get('_last_submission_time', -1)
                st_data['_last_submission_time'] = process_page(url, page, table)

                self._stop = False
                fetch_submissions_user = functools.partial(self.fetch_submissions, fuser)
                for url, page, table, n_page in tqdm(executor.map(fetch_submissions_user, range(2, n_page + 1)),
                                                     total=n_page - 1,
                                                     desc='getting submissions'):
                    if url is None:
                        continue
                    last_st = process_page(url, page, table)
                    if last_st and last_st < limit_st:
                        self._stop = True
                        break

        standings['info_fields'] = ['_last_submission_time']

    def get_standings(self, users=None, statistics=None):

        result = {}

        if users and statistics:
            fusers = users
            for member in users:
                if member not in statistics:
                    continue

                info = deepcopy(statistics.get(member))
                info['member'] = member
                for f in ('place', 'solving', 'upsolving'):
                    info[f] = '__unchanged__'
                result[member] = info

            standings = {'result': result}
        else:
            fusers = []
            page = self._get(self.url)
            match = re.search(r'(?<=<li>)Writer:.*', page)
            writers = []
            if match:
                matches = re.findall('(?<=>)[^<]+(?=<)', match.group())
                writers = list()
                for m in matches:
                    writers.extend(map(str.strip, re.split(r',\s*', m)))
                writers = [w for w in writers if w and w != '?']

            url = f'{self.RESULTS_URL_.format(self)}/'
            page = self._get(url)

            match = re.search(r'var\s*results\s*=\s*(\[[^\n]*\]);$', page, re.MULTILINE)
            data = json.loads(match.group(1))
            results = {}
            for row in data:
                if not row.get('IsRated'):
                    continue
                handle = row.pop('UserScreenName')
                if users and handle not in users:
                    continue
                if 'NewRating' not in row:
                    continue
                r = collections.OrderedDict()
                for k in ['OldRating', 'NewRating', 'Performance']:
                    if k in row:
                        r[k] = row[k]
                results[handle] = r

            url = f'{self.STANDING_URL_.format(self)}/json'
            page = self._get(url)
            data = json.loads(page)

            task_info = collections.OrderedDict()
            for t in data['TaskInfo']:
                k = t['TaskScreenName']
                task_info[k] = {
                    'short': t['Assignment'],
                    'name': t['TaskName'],
                    'url': self.PROBLEM_URL_.format(self, self.key.replace('-', '_'), t['Assignment'].lower()),
                }

            has_rated = False
            has_new_rating = False

            rows = data['StandingsData']
            for row in rows:
                if not row['TaskResults']:
                    continue
                handle = row.pop('UserScreenName')
                if users is not None and handle not in users:
                    continue
                r = result.setdefault(handle, collections.OrderedDict())
                r['member'] = handle
                if row.pop('UserIsDeleted', None):
                    r['action'] = 'delete'
                    continue
                r['place'] = row.pop('Rank')
                total_result = row.pop('TotalResult')

                penalty = total_result['Elapsed'] // 10**9
                r['penalty'] = f'{penalty // 60}:{penalty % 60:02d}'

                r['solving'] = total_result['Score'] / 100.
                r['country'] = row.pop('Country')
                if 'UserName' in row:
                    r['name'] = row.pop('UserName')

                r['url'] = self.SUBMISSIONS_URL_.format(self) + f'?f.User={handle}'

                stats = (statistics or {}).get(handle, {})
                problems = r.setdefault('problems', {})
                solving = 0
                task_results = row.pop('TaskResults', {})
                no_url = False
                for k, v in task_results.items():
                    if 'Score' not in v:
                        continue
                    letter = task_info[k]['short']
                    p = problems.setdefault(letter, stats.get('problems', {}).get(letter, {}))

                    if v['Score'] > 0:
                        solving += 1

                        p['result'] = v['Score'] / 100.

                        seconds = v['Elapsed'] // 10**9
                        p['time'] = f'{seconds // 60}:{seconds % 60:02d}'

                        if v['Penalty'] > 0:
                            p['penalty'] = v['Penalty']
                    else:
                        p['result'] = f"-{v['Failure']}"
                    no_url = no_url or 'url' not in p
                r['solved'] = {'solving': solving}
                if problems and no_url and self.info.get('_last_submission_time', -1) > 0:
                    fusers.append(handle)

                row.update(r)
                row.pop('Additional')
                rating = row.pop('Rating', None)
                if rating is not None:
                    r['info'] = {'rating': rating}
                old_rating = row.pop('OldRating', None)
                r.update(row)

                if handle in results:
                    r.update(results.pop(handle))

                if old_rating is not None and (old_rating or 'NewRating' in r):
                    r['OldRating'] = old_rating

                if r.get('IsRated'):
                    has_rated = True
                    if r.get('NewRating') is not None:
                        has_new_rating = True

            if statistics:
                for member, row in statistics.items():
                    if member not in result:
                        has_result = any('result' in p for p in row.get('problems', {}).values())
                        if has_result:
                            continue
                        row['member'] = member
                        result[member] = row

            standings = {
                'result': result,
                'url': self.STANDING_URL_.format(self),
                'problems': list(task_info.values()),
                'writers': writers,
            }

            if (
                has_rated
                and not has_new_rating
                and self.end_time + timedelta(hours=3) > datetime.utcnow().replace(tzinfo=pytz.utc)
            ):
                standings['timing_statistic_delta'] = timedelta(minutes=30)

        if users or users is None:
            standings['_last_submission_time'] = self.info.get('_last_submission_time', -1)

            self._stop = False
            *_, n_page = self.fetch_submissions()

            if not fusers:
                fusers = [None]
            elif len(fusers) > n_page:
                standings.pop('_last_submission_time')
                fusers = [None]

            self._update_submissions(fusers, standings)

        for row in result.values():
            has_result = any('result' in p for p in row.get('problems', {}).values())
            if has_result:
                row.pop('_no_update_n_contests', None)
            else:
                row['_no_update_n_contests'] = True

        return standings

    @staticmethod
    def get_source_code(contest, problem):
        if 'url' not in problem:
            raise ExceptionParseStandings('Not found url')

        page = REQ.get(problem['url'])
        match = re.search('<pre[^>]*id="submission-code"[^>]*>(?P<source>[^<]*)</pre>', page)
        if not match:
            raise ExceptionParseStandings('Not found source code')
        solution = html.unescape(match.group('source'))
        return {'solution': solution}


if __name__ == '__main__':
    statistic = Statistic(url='https://atcoder.jp/contests/abc150', key='abc150')
    pprint(statistic.get_result('Geothermal'))
    statistic = Statistic(url='https://atcoder.jp/contests/agc031', key='agc031')
    pprint(statistic.get_result('tourist'))
