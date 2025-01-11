#!/usr/bin/env python

import copy
import html
import re
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

import yaml
from django.db.models import Q

from clist.templatetags.extras import as_number, is_yes, slug
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings
from utils.strings import string_iou


def extract_team_name(name):
    match = re.search(r'^(?P<team_name>.*)\([^\)]+\)$', name)
    if not match:
        return
    return match.group('team_name').strip()


class Statistic(BaseModule):

    def _detect_standings(self):
        contest = self.resource.contest_set.filter(end_time__lt=self.start_time)
        contest = contest.filter(standings_url__isnull=False, stage__isnull=True)
        contest = contest.latest('end_time')
        matches = list(re.finditer('[0-9]+', contest.standings_url))
        if not matches:
            raise ExceptionParseStandings('No standings url, not found contest id in previous contest')

        match = matches[-1]
        prefix = contest.standings_url[:match.start()]
        suffix = contest.standings_url[match.end():]
        contest_id = int(match.group())
        for delta in range(1, 30):
            url = f'{prefix}{contest_id + delta}{suffix}'
            page, code = REQ.get(url, return_code=True, ignore_codes={403, 404})
            if code == 403:
                continue
            if code == 404:
                break
            match = re.search('<div[^>]*class="text-center"[^>]*>\s*<h1[^>]*>([^<]+)</h1>', page)
            if not match:
                continue
            title = match.group(1).strip()

            if string_iou(slug(title), slug(self.name)) > 0.95:
                return url

        raise ExceptionParseStandings('No standings url, not found title matching')

    def get_standings(self, users=None, statistics=None, **kwargs):
        if not self.standings_url:
            self.standings_url = self._detect_standings()

        season_ratings = {}
        # season = self.info.get('parse', {}).get('season')
        # if season:
        #     stage = self.info.get('parse', {}).get('stage')
        #     rating_url = urllib.parse.urljoin(self.url, f'/rating?season={season}')
        #     rating_page = REQ.get(rating_url)
        #     table = parsed_table.ParsedTable(rating_page)
        #     for row in table:
        #         rating_idx = None
        #         total_rating = 0
        #         season_rating = None
        #         handle = None
        #         found = False
        #         for k, v in row.items():
        #             k = k.lower()
        #             if rating_idx is not None:
        #                 season_rating = as_number(v.value, force=True)
        #                 if season_rating:
        #                     total_rating += season_rating

        #                 rating_idx += 1
        #                 href = v.header.node.xpath('.//a/@href')
        #                 if not href and str(rating_idx) == stage:
        #                     found = True
        #                     break
        #                 if href and self.standings_url.startswith(href[0]):
        #                     found = True
        #                     break
        #             elif 'team' in k:
        #                 handle = v.value
        #             elif 'rating' in k:
        #                 rating_idx = 0
        #         if found and handle and season_rating:
        #             rating_data = {
        #                 'total_rating': total_rating,
        #                 'season_rating': season_rating,
        #             }
        #             handle = handle.strip()
        #             season_ratings[handle] = rating_data

        #             team_name = extract_team_name(handle)
        #             if team_name in season_ratings:
        #                 season_ratings[team_name] = None
        #             elif team_name:
        #                 season_ratings[team_name] = rating_data

        page = REQ.get(self.standings_url)

        entries = re.findall(r'^([a-z_]+)\s*=\s*(.*);\s*$', page, flags=re.MULTILINE)
        variables = {k: yaml.safe_load(v) for k, v in entries}

        if variables.get('contest_type') != 'ICPC':
            raise ExceptionParseStandings(f'Contest type should be "ICPC", found "{variables["contest_type"]}"')

        standings = variables.pop('standings')
        scorings = variables.pop('score')
        base_url = 'https://qoj.ac/'

        def fetch_problem(problem: tuple[int, int]):
            short, problem_id = problem
            problem_id = str(problem_id)
            problem_info = {'short': short, 'code': problem_id}
            for url in (
                urllib.parse.urljoin(self.standings_url.rstrip('/'), f'problem/{problem_id}'),
                urllib.parse.urljoin(base_url, f'/problem/{problem_id}'),
            ):
                try:
                    problem_page = REQ.get(url)
                    problem_info['url'] = url
                    prefix = rf'(?:#\s*{problem_info["code"]}|{problem_info["short"]})'
                    name = re.search(rf'<h1[^>]*>\s*{prefix}.([^<]+)</h1>', problem_page).group(1)
                    name = html.unescape(name).strip()
                    problem_info['name'] = name
                    break
                except FailOnGetResponse as e:
                    LOG.warn(f'Fail to get problem names: {e}')
            return problem_info

        problems_infos = []
        with PoolExecutor(max_workers=8) as executor:
            problems_short = variables.pop('problems_id')
            for idx in range(len(problems_short)):
                if not problems_short[idx]:
                    problems_short[idx] = chr(ord('A') + idx)
            problems_id = variables.pop('problems')
            problems_data = zip(problems_short, problems_id)
            for problem_info in executor.map(fetch_problem, problems_data):
                problems_infos.append(problem_info)
        variables.pop('my_name', None)

        result = {}
        handle_mapping = {}
        for standings_row in standings:
            solving, penalty, name, rank, rating = standings_row
            if isinstance(name, dict):
                row_data = name
            else:
                row_data = dict(zip(map(str, range(len(name))), name))
            orig_handle, name = row_data.pop('0'), row_data.pop('3')

            scoring = scorings[orig_handle]
            if not scoring:
                continue
            orig_handle = orig_handle.strip()

            for prefix, pattern in (
                ('team-', r'^\$DOM_0*([0-9]+)$'),
                ('team-', '^ucup-team0*([0-9]+)$'),
                (f'{self.key}-team-', r'^\$DEFAULT_DAT_PREFIX_([0-9_]+)$'),
            ):
                match = re.search(pattern, orig_handle)
                if match:
                    handle = f'{prefix}{match.group(1)}'
                    break
            else:
                handle = orig_handle
            if handle in result:
                raise ExceptionParseStandings(f'Duplicate handle "{handle}"')
            handle_mapping[orig_handle] = handle

            name = name.encode('utf8', 'replace').decode('utf8')
            name = re.sub(r'<([a-z]+)[^>]*>.*</\1>$', '', name)
            name = re.sub(r'\(<([a-z]+)[^>]*>.*</\1>\)$', '', name)
            name = name.strip()

            season_ratings_keys = [orig_handle, name, extract_team_name(name)]
            for val in season_ratings_keys:
                rating_data = season_ratings.pop(val, {})
                if rating_data:
                    break

            participant_type = as_number(row_data.pop('2', None))
            row = dict(
                member=handle,
                solving=int(solving) // 100,
                place=rank,
                penalty=penalty // 60,
                name=name,
                original_handle=orig_handle,
                standings_rating=rating,
                rating=row_data.pop('1', None),
                # color=row_data.pop('4', None),
                # rated=row_data.pop('5', None),
                affiliation=row_data.pop('6', None),
                participant_type=participant_type,
                out_of_competition=participant_type in {1, 2},
                **rating_data,
            )

            statistics_problems = (statistics or {}).get(handle, {}).get('problems', {})
            problems = row.setdefault('problems', statistics_problems)
            scoring = scoring.items() if isinstance(scoring, dict) else enumerate(scoring)
            for k, scoring_value in scoring:
                scoring_value, is_hidden = scoring_value[:5], scoring_value[5:]
                score, time, submission_id, n_attempts, full_score = map(int, scoring_value)
                short = problems_infos[int(k)]['short']
                problem = problems.setdefault(short, {})
                is_accepted = score == full_score
                if is_hidden and is_yes(is_hidden[0]):
                    problem['result'] = f'?{n_attempts + 1}'
                elif is_accepted:
                    problem['result'] = f'+{n_attempts}' if n_attempts else '+'
                else:
                    problem['result'] = f'-{n_attempts + 1}'
                if time > 0:
                    problem['time'] = self.to_time(time // 60, num=2)
                    problem['time_in_seconds'] = time
                if submission_id != -1:
                    problem['submission_id'] = submission_id
                    problem['url'] = urllib.parse.urljoin(self.standings_url, f'/submission/{submission_id}')
            result[handle] = row
        if statistics:
            for handle, row in statistics.items():
                if handle not in result:
                    row['member'] = handle
                    result[handle] = copy.deepcopy(row)

        REQ.add_cookie('show_all_submissions', 'true')
        submission_url = urllib.parse.urljoin(self.standings_url.rstrip('/'), 'submissions/')

        seen_pages = {1}
        next_pages = []
        submissions_info = self.info.get('_submissions_info', {})
        last_submission_id = submissions_info.get('last_submission_id') if statistics else None

        def process_submission_page(page):
            try:
                submission_page = REQ.get(submission_url + '?page=' + str(page))
            except FailOnGetResponse as e:
                if page == 1 and e.code == 404:
                    return
                raise e

            table = parsed_table.ParsedTable(submission_page)
            n_added = 0
            for row in table:
                row = {k.lower().replace(' ', '_'): v.value for k, v in row.items()}
                submission_id = int(row.pop('id').lstrip('#'))
                if last_submission_id and submission_id <= last_submission_id:
                    continue
                handle = row.pop('submitter').rstrip(' #')
                short = row.pop('problem').split('.')[0]
                verdict = ''.join(re.findall('[A-Z]', row.pop('result')))
                handle = handle_mapping.get(handle, handle)
                if handle not in result:
                    result[handle] = {'member': handle, 'problems': {}, '_no_update_n_contests': True}
                problems = result[handle].setdefault('problems', {})
                problem = problems.setdefault(short, {})
                is_accepted = verdict == 'AC'
                upsolving = submission_id > problem.get('submission_id', -1)
                if upsolving:
                    problem = problem.setdefault('upsolving', {})
                elif submission_id != problem.get('submission_id', -1):
                    continue

                row['execution_time'] = row.pop('time')
                problem.update(row)
                problem['verdict'] = verdict
                if upsolving:
                    if 'submission_id' not in problem or submission_id > problem['submission_id'] or is_accepted:
                        problem['submission_id'] = submission_id
                        problem['url'] = urllib.parse.urljoin(self.standings_url, f'/submission/{submission_id}')
                    if is_accepted:
                        problem['result'] = f'+{problem.get("attempts") or ""}'
                    else:
                        problem['attempts'] = problem.get('attempts', 0) + 1
                        prev_result = problem.get('result', '-')[0]
                        problem['result'] = f'{prev_result}{problem["attempts"]}'

                if submissions_info.get('last_submission_id', -1) < submission_id:
                    submissions_info['last_submission_id'] = submission_id
                n_added += 1
            if not n_added:
                return

            matches = re.finditer('<a[^>]*class="page-link"[^>]*>(?P<page>[0-9]+)</a>', submission_page)
            for match in matches:
                page = int(match.group('page'))
                if page not in seen_pages:
                    seen_pages.add(page)
                    next_pages.append(page)

        process_submission_page(1)
        with PoolExecutor(max_workers=8) as executor:
            while next_pages:
                curr_pages = next_pages
                next_pages = []
                for _ in executor.map(process_submission_page, curr_pages):
                    pass

        standings = {
            'url': self.standings_url,
            'result': result,
            'problems': problems_infos,
            'hidden_fields': ['total_rating', 'original_handle', 'affiliation', 'rating', 'standings_rating',
                              'out_of_competition'],
            '_submissions_info': submissions_info,
            'info_fields': ['_submissions_info'],
            'options': {'data': variables},
        }
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def set_rename(user, account, ret):
            if re.match('^team-[0-9]+$', user):
                return
            if not account.name:
                return
            match = re.search(r'^(?P<name>.*)\((?P<members>[^\)]*)\)$', account.name)
            if not match:
                return
            name = match.group('name').strip()
            members = [member.strip() for member in match.group('members').split(',')]

            qs = resource.account_set.filter(key__startswith='team-')
            while name and not qs.filter(name__contains=name).exists() and ':' in name:
                name = name.split(':', 1)[1].strip()
            if not name or not (team_qs := qs.filter(name__contains=name)):
                return

            counter = defaultdict(int)
            team_weight = 2
            for team in team_qs:
                counter[team] += team_weight
            member_weight = 1
            for member in members:
                cond = Q(name__contains=member)
                if ' ' in member:
                    rev = ' '.join(reversed(member.split(' ')))
                    cond |= Q(name__contains=rev)
                for team in qs.filter(cond):
                    counter[team] += member_weight
            total_weight = team_weight + max(len(members), 3) * member_weight
            teams = [team for team, count in counter.items() if 2 * count > total_weight]

            if len(teams) > 1:
                season = account.get_last_season()
                same = []
                diff = []
                for team in teams:
                    if team.get_last_season() == season:
                        same.append(team)
                    else:
                        diff.append(team)
                teams = same or diff
                if len(teams) > 1:
                    LOG.warning(f'Found multiple teams = {teams} for {account}')
                    return
            if not teams:
                return
            team = teams[0]
            LOG.info(f'Rename {account} to {team}: name {account.name} to {team.name}')
            ret['rename'] = team.key

        for user, account in zip(users, accounts):
            ret = {'info': {}}
            set_rename(user, account, ret)
            yield ret
            if pbar:
                pbar.update()
