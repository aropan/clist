#!/usr/bin/env python

import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import yaml

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            raise ExceptionParseStandings('No standings url')

        page = REQ.get(self.standings_url)

        entries = re.findall(r'^([a-z_]+)\s*=\s*(.*);\s*$', page, flags=re.MULTILINE)
        variables = {k: yaml.safe_load(v) for k, v in entries}

        if variables['contest_type'] != 'ICPC':
            raise ExceptionParseStandings(f'Contest type should be "ICPC", found "{variables["contest_type"]}"')

        standings = variables.pop('standings')
        scorings = variables.pop('score')
        base_url = 'https://qoj.ac/'

        problems_infos = []
        problems_urls = []
        for idx, problem_id in enumerate(variables['problems']):
            problem_id = str(problem_id)
            url = urllib.parse.urljoin(base_url, f'/problem/{problem_id}')
            problems_urls.append(url)
            problems_infos.append({
                'short': chr(ord('A') + idx),
                'code': problem_id,
                'url': url,
            })
        with PoolExecutor(max_workers=10) as executor:
            for idx, problem_page in enumerate(executor.map(REQ.get, problems_urls)):
                problem = problems_infos[idx]
                name = re.search(rf'<h1[^>]*>\s*#\s*{problem["code"]}.([^<]+)</h1>', problem_page).group(1)
                name = html.unescape(name).strip()
                problem['name'] = name

        result = {}
        for standings_row in standings:
            solving, penalty, name, rank, rating = standings_row
            orig_handle, _, _, name, *_ = name
            handle = orig_handle.strip()
            name = name.encode('utf8', 'replace').decode('utf8')
            name = re.sub(r'<([a-z]+)[^>]*>.*</\1>$', '', name)
            name = name.strip()
            if handle in result:
                raise ExceptionParseStandings(f'Duplicate handle "{handle}"')
            scoring = scorings[orig_handle]
            if not scoring:
                continue

            row = dict(
                member=handle,
                solving=int(solving) // 100,
                place=rank,
                penalty=penalty // 60,
                name=name,
            )

            problems = row.setdefault('problems', {})
            scoring = scoring.items() if isinstance(scoring, dict) else enumerate(scoring)
            for k, scoring_value in scoring:
                score, time, submission_id, n_attemps, full_score, *is_hidden = map(int, scoring_value)
                short = chr(ord('A') + int(k))
                problem = problems.setdefault(short, {})
                is_accepted = score == full_score
                if is_hidden and is_hidden[0]:
                    problem['result'] = f'?{n_attemps + 1}'
                elif is_accepted:
                    problem['result'] = f'+{n_attemps}' if n_attemps else '+'
                else:
                    problem['result'] = f'-{n_attemps + 1}'
                if time >= 0:
                    problem['time'] = self.to_time(time // 60, num=2)
                    problem['time_in_seconds'] = time
                if submission_id != -1:
                    problem['url'] = urllib.parse.urljoin(self.standings_url, f'/submission/{submission_id}')
            result[handle] = row

        standings = {
            'result': result,
            'problems': problems_infos,
        }
        return standings
