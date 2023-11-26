#!/usr/bin/env python

import html
import re
import urllib.parse
from collections import defaultdict

import yaml
from django.db.models import Q

from clist.templatetags.extras import as_number
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


def extract_team_name(name):
    match = re.search(r'^(?P<team_name>.*)\([^\)]+\)$', name)
    if not match:
        return
    return match.group('team_name').strip()


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        if not self.standings_url:
            raise ExceptionParseStandings('No standings url')

        season = self.info.get('parse', {}).get('season')
        season_ratings = {}
        if season:
            stage = self.info.get('parse', {}).get('stage')
            rating_url = urllib.parse.urljoin(self.url, f'/rating?season={season}')
            rating_page = REQ.get(rating_url)
            table = parsed_table.ParsedTable(rating_page)
            for row in table:
                rating_idx = None
                total_rating = 0
                season_rating = None
                handle = None
                for k, v in row.items():
                    k = k.lower()
                    if rating_idx is not None:
                        season_rating = as_number(v.value, force=True)
                        if season_rating:
                            total_rating += season_rating
                        rating_idx += 1
                        if str(rating_idx) == stage:
                            break
                    elif 'team' in k:
                        handle = v.value
                    elif 'rating' in k:
                        rating_idx = 0
                if handle and season_rating:
                    rating_data = {
                        'total_rating': total_rating,
                        'season_rating': season_rating,
                    }
                    handle = handle.strip()
                    season_ratings[handle] = rating_data

                    team_name = extract_team_name(handle)
                    if team_name in season_ratings:
                        season_ratings[team_name] = None
                    elif team_name:
                        season_ratings[team_name] = rating_data

        page = REQ.get(self.standings_url)

        entries = re.findall(r'^([a-z_]+)\s*=\s*(.*);\s*$', page, flags=re.MULTILINE)
        variables = {k: yaml.safe_load(v) for k, v in entries}

        if variables['contest_type'] != 'ICPC':
            raise ExceptionParseStandings(f'Contest type should be "ICPC", found "{variables["contest_type"]}"')

        standings = variables.pop('standings')
        scorings = variables.pop('score')
        base_url = 'https://qoj.ac/'

        problems_infos = []
        for idx, problem_id in enumerate(variables['problems']):
            problem_id = str(problem_id)
            problem_info = {'short': chr(ord('A') + idx), 'code': problem_id}
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
            problems_infos.append(problem_info)

        result = {}
        for standings_row in standings:
            solving, penalty, name, rank, rating = standings_row
            orig_handle, _, _, name, *_ = name
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

            name = name.encode('utf8', 'replace').decode('utf8')
            name = re.sub(r'<([a-z]+)[^>]*>.*</\1>$', '', name)
            name = name.strip()

            season_ratings_keys = [orig_handle, name, extract_team_name(name)]
            for val in season_ratings_keys:
                rating_data = season_ratings.pop(val, {})
                if rating_data:
                    break

            row = dict(
                member=handle,
                solving=int(solving) // 100,
                place=rank,
                penalty=penalty // 60,
                name=name,
                original_handle=orig_handle,
                **rating_data,
            )

            problems = row.setdefault('problems', {})
            scoring = scoring.items() if isinstance(scoring, dict) else enumerate(scoring)
            for k, scoring_value in scoring:
                score, time, submission_id, n_attempts, full_score, *is_hidden = map(int, scoring_value)
                short = chr(ord('A') + int(k))
                problem = problems.setdefault(short, {})
                is_accepted = score == full_score
                if is_hidden and is_hidden[0]:
                    problem['result'] = f'?{n_attempts + 1}'
                elif is_accepted:
                    problem['result'] = f'+{n_attempts}' if n_attempts else '+'
                else:
                    problem['result'] = f'-{n_attempts + 1}'
                if time > 0:
                    problem['time'] = self.to_time(time // 60, num=2)
                    problem['time_in_seconds'] = time
                if submission_id != -1:
                    problem['url'] = urllib.parse.urljoin(self.standings_url, f'/submission/{submission_id}')
            result[handle] = row

        standings = {
            'result': result,
            'problems': problems_infos,
            'hidden_fields': ['total_rating', 'original_handle'],
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
            total_weight = team_weight + len(members) * member_weight
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
