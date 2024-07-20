import html
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from urllib.parse import urljoin

from ratelimiter import RateLimiter

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        if self.standings_url is None:
            raise ExceptionParseStandings('Standings url is none')

        cid = self.standings_url.strip('/').split('/')[-1]
        limit = 100

        def fetch_problems():
            offset = 0
            total = None
            problems_infos = OrderedDict()
            while total is None or offset < total:
                url = f'https://algotester.com/en/ContestProblem/DisplayList/{cid}?actions=4&offset={offset}&limit={limit}'  # noqa
                page = REQ.get(url, headers={'x-requested-with': 'XMLHttpRequest'})
                data = json.loads(page)
                if total is None:
                    if 'total' not in data:
                        return
                    total = data['total']
                if 'rows' not in data:
                    return

                for problem in data['rows']:
                    code = str(problem['Id'])
                    problem_info = problems_infos.setdefault(code, {})
                    problem_info['code'] = code
                    problem_info['short'] = html.unescape(problem['Name'])
                    problem_info['name'] = html.unescape(problem['Problem'])
                    for action in problem['Actions']:
                        if action['Text'] == 'View':
                            problem_info['url'] = urljoin(url, action['Url'])
                offset += limit
            return problems_infos

        problems_infos = fetch_problems()
        if problems_infos is None:
            problems_infos = OrderedDict()
            page = REQ.get(self.standings_url)
            matches = re.finditer('<th[^>]*(?:data-field="(?P<field>[^"]*)"[^>]*|data-formatter="(?P<formatter>[^"]*)"[^>]*){2}>(?P<value>[^<]*)</th>', page)  # noqa
            for match in matches:
                formatter = match.group('formatter')
                if formatter.startswith('formatter'):
                    code = formatter[len('formatter'):]
                    short = match.group('field')
                    name = match.group('value')
                    problems_infos[code] = {'code': code,
                                            'short': html.unescape(short),
                                            'name': html.unescape(name)}

        @RateLimiter(max_calls=5, period=1)
        def fetch_page(page):
            offset = (page - 1) * limit
            url = f'https://algotester.com/en/Contest/ListScoreboard/{cid}?offset={offset}&limit={limit}'
            page = REQ.get(url, headers={'x-requested-with': 'XMLHttpRequest'})
            data = json.loads(page)
            return data

        result = {}
        hidden_fields = {'element_type', 'is_unofficial', 'group_ex'}
        problems_results = set()
        unofficials = set()

        def proccess_data(data):
            nonlocal result, hidden_fields
            for row in data['rows']:
                contestant = row.pop('Contestant')
                url = contestant.pop('Url')
                match = re.search('(?P<type>Account|Team)/Display/(?P<key>[0-9]+)', url)
                handle = match.group('type').lower() + match.group('key')
                r = result.setdefault(handle, OrderedDict())
                r['member'] = handle
                r['name'] = contestant.pop('Text')
                info = r.setdefault('info', {})
                info['profile_url'] = {'path': url}

                r['place'] = row.pop('Rank')
                r['solving'] = row.pop('Score')

                penalty = row.pop('PenaltyMs') / 1000
                r['penalty'] = self.to_time(penalty, num=3)

                group = row.pop('Group')
                if group:
                    r['group'] = group['Text']

                group_ex = row.pop('GroupEx')
                if group_ex:
                    r['group_ex'] = group_ex['Text']
                    if group_ex['Url'] and '/flags/circular/' in group_ex['Url']:
                        r['country'] = r.pop('group_ex')

                r['is_unofficial'] = row.pop('IsUnofficial')
                unofficials.add(r['is_unofficial'])
                r['element_type'] = row.pop('ElementType')

                if self.invisible:
                    r['_no_update_n_contests'] = True

                problems = r.setdefault('problems', {})
                solved = 0
                for code, res in row['Results'].items():
                    if code not in problems_infos:
                        continue
                    short = problems_infos[code]['short']
                    problem = problems.setdefault(short, {})
                    problems_results.add(res['Score'])
                    problem['result'] = res['Score']
                    penalty = res.pop('LastImprovementMs') / 1000
                    problem['time'] = self.to_time(penalty / 60, num=2)
                    problem['time_in_seconds'] = penalty
                    problem['partial'] = not res['IsAccepted']
                    problem['attempts'] = res['Attempts']
                    problem['pending'] = res['PendingAttempts']
                    if not problem['partial']:
                        solved += 1
                r['solved'] = {'solving': solved}

        data = fetch_page(1)
        if 'rows' not in data:
            raise ExceptionParseStandings(json.dumps(data))
        proccess_data(data)

        with PoolExecutor(max_workers=4) as executor:
            total_pages = (data['total'] + limit - 1) // limit
            for data in executor.map(fetch_page, range(2, total_pages + 1)):
                proccess_data(data)

        if problems_results.issubset({0, 1}):
            for r in result.values():
                for problem in r['problems'].values():
                    attempts = problem.pop('attempts')
                    pending = problem.pop('pending')
                    if problem['result']:
                        problem['result'] = f'+{attempts}' if attempts else '+'
                    elif pending:
                        problem['result'] = f'?{pending}'
                    else:
                        problem['result'] = f'-{attempts}'

        standings = {
            'result': result,
            'hidden_fields': list(hidden_fields),
            'problems': list(problems_infos.values()),
        }

        if len(unofficials) == 2:
            for r in result.values():
                r['division'] = 'unofficial' if r.pop('is_unofficial') else 'official'
            standings['divisions_order'] = ['official', 'unofficial']

        return standings
