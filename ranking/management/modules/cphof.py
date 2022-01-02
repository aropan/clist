#!/usr/bin/env python

import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import timedelta
from urllib.parse import unquote, urljoin, urlparse

from django.db.models import Q
from tqdm import tqdm

from clist.models import Contest
from clist.templatetags.extras import as_number
from ranking.management.modules.common import REQ, BaseModule, parsed_table


class Statistic(BaseModule):

    def get_standings(self, users=None, statistics=None):
        standings_url = self.standings_url or self.url
        page = REQ.get(standings_url)

        standings = {'url': standings_url}
        options = standings.setdefault('options', {'parse': {}})

        regex = '<table>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        if match:
            html_table = match.group(0)
            table = parsed_table.ParsedTable(html_table, without_header=True, ignore_wrong_header_number=False)
            infos = {}
            for r in table:
                k, v = [col.value for col in r.columns]
                k = k.strip(':').lower().replace(' ', '_')
                infos[k] = v
            options['parse'] = infos

        def find_related(statistics):
            infos = deepcopy(self.info.get('standings', {}).get('parse', {}))

            if '_related' in infos and Contest.objects.get(pk=infos['_related']):
                options['parse']['_related'] = infos['_related']
                return

            related = None

            infos.update(options.get('parse', {}))

            host_mapping = self.resource.info['_host_mapping']
            host = infos.get('official_page')
            if host:
                match = re.search('.*https?://(?P<host>[^/]*)/', host)
                host = match.group('host')
            else:
                host = infos.get('series')

            ignore_n_statistics = False
            ignore_title = None
            for mapping in host_mapping:
                if re.search(mapping['regex'], host):
                    host = mapping['host']
                    ignore_title = mapping.get('ignore_title')
                    ignore_n_statistics = mapping.get('ignore_n_statistics', ignore_n_statistics)
                    break
            if host:
                delta_start = timedelta(days=3)
                qs = Contest.objects.filter(resource__host=host)
                qs = qs.filter(
                    Q(start_time__gte=self.start_time - delta_start, start_time__lte=self.start_time + delta_start) |
                    Q(end_time__gte=self.start_time - delta_start, end_time__lte=self.start_time + delta_start)
                )

                if not ignore_n_statistics:
                    teams = set()
                    for r in statistics.values():
                        if 'team_id' in r:
                            teams.add(r['team_id'])
                    n_statistics = len(teams) if teams else len(statistics)
                    delta_n = round(n_statistics * 0.15)
                    qs = qs.filter(n_statistics__gte=n_statistics - delta_n, n_statistics__lte=n_statistics + delta_n)

                if ignore_title:
                    qs = qs.exclude(title__iregex=ignore_title)

                if len(qs) > 1:
                    first = None
                    for stat in statistics.values():
                        if stat.get('place') == '1':
                            first = stat['member'].split(':', 1)[-1]
                    qs = qs.filter(statistics__place_as_int=1, statistics__account__key=first)

                if len(qs) == 1:
                    related = qs.first().pk

            if related is not None:
                options['parse']['_related'] = related
                standings['invisible'] = True
            else:
                standings['invisible'] = False

        regex = '<table[^>]*class="[^"]*table[^"]*"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)

        profile_urls = {}
        for r in table:
            row = OrderedDict()
            rank = r.pop('Rank')
            row['place'] = rank.value
            medal = rank.column.node.xpath('.//img[contains(@alt,"medal")]/@title')
            if medal:
                row['medal'] = medal[0].lower()

            name_key = 'Name' if 'Name' in r else 'Team'
            name = r.pop(name_key)
            members = name.column.node.xpath('.//a')
            val = name.value
            if name_key == 'Team':
                if ':' in val:
                    val = val.rsplit(': ', 1)[0]
                row['team_id'] = val
            row['name'] = val

            val = r.pop('Score').value.strip()
            row['solving'] = as_number(val) if val and val != '?' else 0

            row['_no_update_name'] = True

            for k, v in r.items():
                k = k.lower()
                if k in row:
                    continue
                v = v.value.strip()
                if not v or v == '?':
                    continue
                row[k.lower()] = as_number(v)

            for member in members:
                url = urljoin(standings_url, member.attrib['href'])
                row['_profile_url'] = url
                profile_urls[url] = deepcopy(row)

        statistics_profiles_urls = {}
        if statistics:
            for s in statistics.values():
                if '_profile_url' in s:
                    statistics_profiles_urls[s['_profile_url']] = s

        def get_handle(row):
            url = row['_profile_url']
            if 'university' in url:
                row['_skip'] = True

            if url in statistics_profiles_urls:
                stat = statistics_profiles_urls[url]
                for k, v in stat.items():
                    if k not in row:
                        row[k] = v
                if '_member' in row and '_info' in row:
                    row['member'] = row['_member']
                    row['info'] = row['_info']
                    return row

            page = REQ.get(url)
            info = row.setdefault('info', {})

            if 'university' in url:
                handle = unquote(urlparse(url).path)
                handle = handle.strip('/')
                handle = handle.replace('/', ':')
                row['member'] = handle
            else:
                match = re.search('<link[^>]*rel="canonical"[^>]*href="[^"]*/profile/(?P<handle>[^"]*)"[^>]*>', page)
                handle = match.group('handle')
                row['member'] = handle

                match = re.search(r'>[^<]*prize[^<]*money[^<]*(?:<[^>]*>)*[^<]*\$(?P<val>[.0-9]+)', page, re.IGNORECASE)
                if match:
                    info['prize_money'] = as_number(match.group('val'))

                match = re.search(r'>country:</[^>]*>(?:\s*<[^>]*>)*\s*<a[^>]*href="[^"]*/country/(?P<country>[^"]*)"',
                                  page, re.IGNORECASE)
                if match:
                    info['country'] = match.group('country')

            match = re.search('<h3[^>]*>(?P<name>[^>]*)<', page)
            info['name'] = match.group('name').strip()

            row['_member'] = row['member']
            row['_info'] = dict(info)

            return row

        result = {}
        members = defaultdict(list)
        with PoolExecutor(max_workers=4) as executor, tqdm(total=len(result), desc='urls') as pbar:
            for row in executor.map(get_handle, profile_urls.values()):
                pbar.update()
                result[row['member']] = row

                skip = row.pop('_skip', False)
                if not skip and 'team_id' in row:
                    members[row['team_id']].append({'account': row['member'], 'name': row['info']['name']})

        if members:
            for row in result.values():
                if 'team_id' in row:
                    row['_members'] = members[row['team_id']]

        find_related(result)

        standings['result'] = result
        return standings
