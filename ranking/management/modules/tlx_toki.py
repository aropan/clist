# -*- coding: utf-8 -*-

import collections
import json
import itertools
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from contextlib import ExitStack

import tqdm

from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    STANDING_URL_FORMAT_ = '{0.url}/scoreboard'
    PROBLEM_URL_FORMAT_ = '{url}/problems/{short}'
    CONFIG_URL_FORMAT_ = 'https://api.tlx.toki.id/v2/contest-web/slug/{slug}/with-config'
    API_STANDINGS_URL_FORMAT_ = 'https://api.tlx.toki.id/v2/contests/{jid}/scoreboard?frozen=false&showClosedProblems=false'  # noqa
    API_PROBLEMS_URL_FORMAT_ = 'https://api.tlx.toki.id/v2/contests/{jid}/problems'
    API_HISTORY_URL_FORMAT_ = 'https://api.tlx.toki.id/v2/contest-history/public?username={handle}'

    def __init__(self, **kwargs):
        super(Statistic, self).__init__(**kwargs)

    def get_standings(self, users=None, statistics=None):
        slug = self.url.rstrip('/').rsplit('/', 1)[-1]
        config_url = self.CONFIG_URL_FORMAT_.format(slug=slug)
        page = REQ.get(config_url)
        config_data = json.loads(page)
        style = config_data['contest']['style'].upper()

        jid = config_data['contest']['jid']
        url = self.API_STANDINGS_URL_FORMAT_.format(jid=jid)
        page = REQ.get(url)
        data = json.loads(page)
        users_profiles_map = data['profilesMap']

        problems_url = self.API_PROBLEMS_URL_FORMAT_.format(jid=jid)
        problems_data = json.loads(REQ.get(problems_url))

        problems_info = []
        state = data['data']['scoreboard']['state']
        for idx, (code, short, problem_data) in enumerate(
            zip(state['problemJids'], state['problemAliases'], problems_data['data'])
        ):
            problem_data.update(problems_data['problemsMap'][problem_data['problemJid']])
            title = problem_data['titlesByLanguage'][problem_data['defaultLanguage']]
            info = {
                'name': title,
                'code': problem_data['slug'],
                'short': short,
            }
            if state['problemPoints']:
                info['full_score'] = state['problemPoints'][idx]
            elif problem_data['points']:
                info['full_score'] = problem_data['points']
            info['url'] = self.PROBLEM_URL_FORMAT_.format(url=self.url, short=info['short'])
            problems_info.append(info)

        result = {}
        if users is None or users:
            rows = data['data']['scoreboard']['content']['entries']
            handles_to_get_new_rating = []
            has_old_rating = False
            for row in rows:
                cjid = row['contestantJid']
                if cjid not in users_profiles_map:
                    continue
                user = users_profiles_map[cjid]
                handle = user['username']

                r = result.setdefault(handle, collections.OrderedDict())
                r['member'] = handle
                r['place'] = row.pop('rank')
                if user.get('country'):
                    r['country'] = user['country']

                if style == 'ICPC':
                    r['penalty'] = row.pop('totalPenalties')
                    r['solving'] = row.pop('totalAccepted')
                elif style == 'GCJ':
                    penalty = row.pop('totalPenalties')
                    r['penalty'] = f'{penalty // 60:02d}:{penalty % 60:02d}'
                    r['solving'] = row.pop('totalPoints')
                elif style == 'IOI':
                    r['solving'] = row.pop('totalScores')
                else:
                    raise ExceptionParseStandings(f'style = {style}')

                problems = r.setdefault('problems', {})
                solving = 0
                if style == 'IOI':
                    for idx, score in enumerate(row['scores']):
                        if score is None:
                            continue
                        k = problems_info[idx]['short']
                        p = problems.setdefault(k, {})
                        p['result'] = score
                        p['partial'] = problems_info[idx].get('full_score', 100) > score
                        if not p['partial']:
                            solving += 1
                else:
                    for idx, (attempt, penalty, pstate) in enumerate(
                        zip(row['attemptsList'], row['penaltyList'], row['problemStateList'])
                    ):
                        if not attempt:
                            continue
                        k = problems_info[idx]['short']
                        p = problems.setdefault(k, {})

                        if pstate:
                            solving += 1
                            p['result'] = f"+{'' if attempt == 1 else attempt - 1}"
                            p['time'] = f'{penalty // 60:02d}:{penalty % 60:02d}'
                        else:
                            p['result'] = f"-{attempt}"
                        if pstate == 2:
                            p['first_ac'] = True
                if not problems:
                    result.pop(handle)
                    continue

                if state['problemPoints'] or style == 'IOI':
                    r['solved'] = {'solving': solving}

                r['old_rating'] = (user.get('rating') or {}).get('publicRating')
                if r['old_rating'] is not None:
                    has_old_rating = True

                if statistics is None or 'new_rating' not in statistics.get(handle, {}):
                    handles_to_get_new_rating.append(handle)
                else:
                    r['new_rating'] = statistics[handle]['new_rating']

            if not has_old_rating:
                for r in result.values():
                    r.pop('old_rating')

            with ExitStack() as stack:
                executor = stack.enter_context(PoolExecutor(max_workers=8))
                pbar = stack.enter_context(tqdm.tqdm(total=len(handles_to_get_new_rating), desc='getting new rankings'))

                def fetch_data(handle):
                    url = self.API_HISTORY_URL_FORMAT_.format(handle=handle)
                    data = json.loads(REQ.get(url))
                    return handle, data

                for handle, data in executor.map(fetch_data, handles_to_get_new_rating):
                    max_begin_time = -1
                    for contest in data['data']:
                        if contest['rating']:
                            rating = contest['rating']['publicRating']

                            if contest['contestJid'] == jid:
                                result[handle]['new_rating'] = rating

                            info = data['contestsMap'][contest['contestJid']]
                            if info['beginTime'] > max_begin_time:
                                result[handle]['info'] = {'rating': rating}
                                max_begin_time = info['beginTime']
                    pbar.update()

        standings = {
            'result': result,
            'url': self.STANDING_URL_FORMAT_.format(self),
            'problems': problems_info,
        }
        return standings


if __name__ == '__main__':
    statistic = Statistic(url='https://tlx.toki.id/contests/troc-11-div-1', key='380')
    standings = statistic.get_standings()
    result = standings.pop('result', {})
    pprint(list(itertools.islice(result.items(), 0, 10)))
