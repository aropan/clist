#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ, BaseModule

from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import json
from datetime import datetime


class Statistic(BaseModule):
    API_RANKING_URL_FORMAT_ = 'https://leetcode.com/contest/api/ranking/{key}/?pagination={{}}'
    RANKING_URL_FORMAT_ = '{url}/ranking'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None):
        standings_url = self.standings_url or self.RANKING_URL_FORMAT_.format(**self.__dict__)

        api_ranking_url_format = self.API = self.API_RANKING_URL_FORMAT_.format(**self.__dict__)
        url = api_ranking_url_format.format(1)
        content = REQ.get(url)
        data = json.loads(content)
        if not data:
            return {'result': {}, 'url': standings_url}
        n_page = (data['user_num'] - 1) // len(data['total_rank']) + 1

        def fetch_page(page):
            url = api_ranking_url_format.format(page)
            content = REQ.get(url)
            return json.loads(content)

        start_time = self.start_time.replace(tzinfo=None)
        result = {}
        with PoolExecutor(max_workers=8) as executor:
            for data in executor.map(fetch_page, range(1, n_page)):
                problem_infos = {d['question_id']: d for d in data['questions']}
                for row, submissions in zip(data['total_rank'], data['submissions']):
                    if not submissions:
                        continue
                    handle = row.pop('username')
                    row.pop('contest_id')
                    row.pop('user_slug')
                    row.pop('global_ranking')
                    row.pop('data_region')

                    r = result.setdefault(handle, {})
                    r['member'] = handle
                    r['place'] = row.pop('rank')
                    r['solving'] = row.pop('score')

                    solved = 0
                    problems = r.setdefault('problems', {})
                    for i, (k, s) in enumerate(submissions.items()):
                        p = problems.setdefault(f'Q{i + 1}', {})
                        p['time'] = self.to_time(datetime.fromtimestamp(s['date']) - start_time)
                        if s['status'] == 10:
                            solved += 1
                            p['result'] = '+' + str(s['fail_count'] or '')
                        else:
                            p['result'] = f'-{s["fail_count"]}'
                        p['name'] = problem_infos[int(k)]['title']
                    r['solved'] = {'solving': solved}
                    finish_time = datetime.fromtimestamp(row.pop('finish_time')) - start_time
                    r['penalty'] = self.to_time(finish_time)
                    r.update(row)

        standings = {
            'result': result,
            'url': standings_url,
        }
        return standings


if __name__ == "__main__":
    statictic = Statistic(
        name='Weekly Contest 135',
        url='https://leetcode.com/contest/weekly-contest-135',
        key='weekly-contest-135',
        start_time=datetime.now(),
        standings_url=None,
    )
    from pprint import pprint
    pprint(statictic.get_standings())
