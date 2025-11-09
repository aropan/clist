#!/usr/bin/env python3

import re

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from utils.requester import FailOnGetResponse


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.standings_url:
            raise ExceptionParseStandings("No standings URL provided")

        page = REQ.get(self.standings_url)
        header_mapping = {
            '': 'place',
            '#': 'place',
            'Participant': 'name',
            'Team': 'name',
            'Total': 'solving',
            '=': 'solving',
        }
        table = parsed_table.ParsedTable(page, as_list=True, header_mapping=header_mapping)

        season = self.get_season()
        result = {}
        problem_infos = {}
        for row in table:
            r = {}
            problems = r.setdefault('problems', {})
            for k, v in row:
                k_parts = k.split()
                if '_top_column' in v.header.attrs:
                    short = v.header.attrs['_top_column'].value
                    *idx, full_score, best_score = k.split()
                    if idx:
                        short = f'{short}{idx[0]}'
                    if short not in problems:
                        problem_infos[short] = {'short': short, 'full_score': full_score, 'best_score': best_score}
                    if not v.value:
                        continue
                    value, best_score = v.value.split()
                    problems[short] = {
                        'result': as_number(value),
                        'best_score': as_number(best_score),
                    }
                elif len(k_parts) == 2 and len(k_parts[0]) == 1 and k_parts[0].isalpha() and as_number(k_parts[1]):
                    short = k_parts[0]
                    if short not in problems:
                        problem_infos[short] = {'short': short, 'full_score': as_number(k_parts[1])}
                    score = as_number(v.value, force=True)
                    if score is not None:
                        problems[short] = {'result': score}
                else:
                    r[k] = v.value
            member = f'{r["name"]} {season}'
            r['member'] = member
            r['info'] = {'is_team': True}
            result[member] = r

        if self.standings_url.endswith('/standings/'):
            for short, problem_info in problem_infos.items():
                try:
                    problem_url = self.standings_url.replace('/standings/', f'/problems/{short}/')
                    problem_page, problem_url = REQ.get(problem_url, return_url=True)
                    match = re.search('<h1[^>]*>(?P<name>.*?)</h1>', problem_page)
                    problem_name = match.group('name')

                    def strikethrough(m):
                        return ''.join(c + '\u0336' for c in m.group(1))
                    problem_name = re.sub(r'<del>(.*?)</del>', strikethrough, problem_name)

                    problem_info['name'] = problem_name
                    problem_info['url'] = problem_url
                except FailOnGetResponse:
                    pass

        self.complete_result(result)
        for row in result.values():
            if 'members' in row:
                row['_members'] = [{'name': m} for m in row.pop('members')]

        standings = {
            'result': result,
            'problems': list(problem_infos.values()),
        }
        return standings
