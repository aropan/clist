#!/usr/bin/env python
# -*- coding: utf-8 -*-

from common import REQ
from common import BaseModule
from excepts import ExceptionParseStandings
import conf

import time
import json


class Statistic(BaseModule):
    API_CONTEST_URL_FORMAT_ = 'https://www.codechef.com/api/contests/{key}'
    API_RANKING_URL_FORMAT_ = 'https://www.codechef.com/api/rankings/{key}?sortBy=rank&order=asc&page={page}&itemsPerPage={per_page}'  # noqa

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)
        self._username = conf.CODECHEF_USERNAME
        self._password = conf.CODECHEF_PASSWORD

    def get_standings(self, users=None):
        REQ.get('https://www.codechef.com/')

        try:
            form = REQ.form()
            form['post'].update({
                'name': self._username,
                'pass': self._password,
            })
            page = REQ.get(form['url'], post=form['post'])

            form = REQ.form()
            if form['url'] == '/session/limit':
                for field in form['unchecked'][:-1]:
                    form['post'][field['name']] = field['value'].encode('utf8')
                page = REQ.get(form['url'], post=form['post'])
        except Exception:
            pass

        url = self.API_CONTEST_URL_FORMAT_.format(**self.__dict__)
        page = REQ.get(url)
        data = json.loads(page)
        if data['status'] != 'success':
            raise ExceptionParseStandings(json.dumps(data))
        if 'child_contests' in data:
            contest_infos = {
                d['contest_code']: {'division': k}
                for k, d in data['child_contests'].items()
            }
        else:
            contest_infos = {self.key: {}}

        result = {}

        for key, contest_info in contest_infos.items():
            n_page = 0
            per_page = 150
            total = None
            while total is None or n_page * per_page < total:
                n_page += 1
                time.sleep(3)
                url = self.API_RANKING_URL_FORMAT_.format(key=key, page=n_page, per_page=per_page)

                delay = 30
                while True:
                    try:
                        page = REQ.get(url)
                        data = json.loads(REQ.get(url))
                        break
                    except Exception:
                        delay *= 2
                        print('Sleep:', delay, end='. ')
                        time.sleep(delay)
                        print('Done')

                if 'status' in data and data['status'] != 'success':
                    raise ExceptionParseStandings(json.dumps(data))

                if total is None:
                    total = data['totalItems']
                problem_info = {}
                for p in data['problems']:
                    code = p.pop('code')
                    problem_info[code] = p
                unscored_problems = data['contest_info']['unscored_problems']

                for d in data['list']:
                    handle = d.pop('user_handle')
                    if d['score'] < 1e-9:
                        continue
                    row = result.setdefault(handle, {})

                    row['member'] = handle
                    row['place'] = d.pop('rank')
                    row['solving'] = int(round(d['score']))
                    score = d.pop('score')
                    if not isinstance(score, int):
                        row['score'] = score

                    d.pop('html_handle')

                    problems = row.setdefault('problems', {})
                    solved, upsolved = 0, 0
                    problems_status = d.pop('problems_status')
                    if problems_status:
                        for k, v in problems_status.items():
                            v['upsolving' if k in unscored_problems else 'result'] = v.pop('score')
                            solved += 1 if v.get('result', 0) > 0 else 0
                            upsolved += 1 if v.get('upsolving', 0) > 0 else 0
                            v.update(problem_info[k])
                            row['solved'] = {'solving': solved, 'upsolving': upsolved}
                            problems[k] = v

                    row.update(d)
                    row.update(contest_info)

        standings = {
            'result': result,
            'url': self.url,
        }
        return standings


if __name__ == "__main__":
    REQ.debug_output = True
    statictic = Statistic(
        name='April Challenge 2019',
        url='http://www.codechef.com/APRIL19?utm_source=contest_listing&utm_medium=link&utm_campaign=APRIL19',
        key='APRIL19',
        standings_url=None,
    )
    from pprint import pprint
    pprint(statictic.get_standings())
