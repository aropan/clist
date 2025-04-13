#!/usr/bin/env python3

from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.standings_url:
            raise ExceptionParseStandings("No standings URL provided")

        page = REQ.get(self.standings_url)
        header_mapping = {
            '': 'place',
            'Participant': 'name',
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
                else:
                    r[k] = v.value
            member = f'{r["name"]} {season}'
            r['member'] = member
            r['info'] = {'is_team': True}
            result[member] = r

        self.complete_result(result)
        for row in result.values():
            if 'members' in row:
                row['_members'] = [{'name': m} for m in row.pop('members')]

        standings = {
            'result': result,
            'problems': list(problem_infos.values()),
        }
        return standings
