# -*- coding: utf-8 -*-

import collections
import re
import urllib.parse
from copy import deepcopy

import arrow

from clist.templatetags.extras import as_number, html_unescape
from ranking.management.modules.common import REQ, BaseModule, parsed_table
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None, **kwargs):
        url_info = urllib.parse.urlparse(self.url)
        if (
            not url_info.hostname.endswith('azspcs.com') or
            not url_info.path.startswith('/Contest/')
        ):
            return {'action': 'skip'}

        standings_url = self.url.rstrip('/') + '/Standings'
        page = REQ.get(standings_url)

        matches = re.finditer(
            r'''
            <a[^>]*id="(?P<id>[^"]*)[^>]*>[^<]*</a>\s*
            <sup[^>]*>(?P<team>[^<]*)</sup>[^<]*
            <ul[^>]*>(?P<members>.*?)</ul>
            ''',
            page,
            re.VERBOSE | re.DOTALL,
        )
        teams = {}
        for match in matches:
            team = match.group('team').strip()
            team_id = match.group('id')
            members = []
            for match in re.finditer('<li[^>]*>(?P<member>.*?)</li>', match.group('members')):
                groups = re.search(r'<[^>]*userid="([^"]*)"[^>]*>([^<]*)</', match.group('member')).groups()
                handle, name = map(str.strip, groups)
                location = re.search(r'\((?P<loc>[^\)]*)\)', match.group('member')).group('loc').strip()
                country = location.split(',')[-1].strip()
                member = {
                    'team_id': team_id,
                    'member': handle,
                    'location': location,
                    '_account_name': name,
                    '_field_update_name': '_account_name',
                    'country': country,
                }
                members.append(member)
            teams[team] = members

        tables = re.finditer(r'(?P<table><table[^>]*>.*?</table>)', page, re.DOTALL)
        result = collections.OrderedDict()
        for table in tables:
            rows = parsed_table.ParsedTable(table.group('table'))
            for row in rows:
                if 'Rank' not in row:
                    continue
                r = {}
                r['place'] = as_number(row['Rank'].value)
                r['solving'] = as_number(row['Score'].value)
                submit_time = arrow.get(html_unescape(row['Last Improvement'].value), 'D MMM YYYY HH:mm')
                r['submit_time'] = int(submit_time.timestamp())

                contestant = row['Contestant'][0]
                location = row['Contestant'][1].value
                sup = contestant.column.node.xpath('.//sup/a')
                if sup:
                    team = sup[0].text.strip()
                    r['name'] = contestant.value.strip(team).strip()
                    location = location.strip(team).strip()
                    team = teams.pop(team)
                    members = [{'account': member['member'], 'country': member['country']} for member in team]
                    for member in team:
                        r_copy = deepcopy(r)
                        r_copy.update(member)
                        r_copy['_members'] = members
                        r_copy['location'] = location
                        r_copy.pop('country')
                        result[member['member']] = r_copy
                else:
                    user = contestant.column.node.xpath('.//*[@userid]')
                    if not user:
                        raise ExceptionParseStandings('Not found user')
                    if len(user) > 1:
                        raise ExceptionParseStandings('More than one user')
                    r['location'] = location
                    r['country'] = location.split(',')[-1].strip()
                    user = user[0]
                    handle = user.get('userid')
                    name = user.text
                    r['member'] = handle
                    r['name'] = name
                    result[handle] = r

        standings = {
            'result': result,
            'url': standings_url,
            'hidden_fields': ['location'],
            'fields_types': {'submit_time': ['timestamp']},
        }
        if self.contest.is_over():
            options = standings.setdefault('options', {})
            options['medals'] = [{'name': name, 'count': 1} for name in ('gold', 'silver', 'bronze')]
        return standings
