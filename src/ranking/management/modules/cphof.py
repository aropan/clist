#!/usr/bin/env python

import html
import re
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor as PoolExecutor
from copy import deepcopy
from datetime import timedelta
from urllib.parse import unquote, urljoin, urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from tqdm import tqdm

from clist.models import Contest, Resource
from clist.templatetags.extras import as_number
from notification.models import NotificationMessage
from ranking.management.modules.common import LOG, REQ, BaseModule, FailOnGetResponse, parsed_table
from ranking.management.modules.excepts import ExceptionParseAccounts
from true_coders.models import Coder
from utils.timetools import parse_duration


class Statistic(BaseModule):

    @staticmethod
    def _parse_profile_page(url):
        page = REQ.get(url)
        info = {}

        info['profile_url'] = {'type': urlparse(url).path.split('/')[1]}
        if '/profile/' not in url:
            handle = unquote(urlparse(url).path)
            handle = handle.strip('/')
            handle = handle.replace('/', ':')
            info['member'] = handle
            info['profile_url']['account'] = handle.split(':', 1)[1]
        else:
            match = re.search('<link[^>]*rel="canonical"[^>]*href="[^"]*/profile/(?P<handle>[^"]*)"[^>]*>', page)
            handle = match.group('handle')
            info['member'] = html.unescape(handle)

            match = re.search(r'>[^<]*prize[^<]*money[^<]*(?:<[^>]*>)*[^<]*\$(?P<val>[.0-9]+)', page, re.IGNORECASE)
            if match:
                info['prize_money'] = as_number(match.group('val'))

            match = re.search(r'>country:</[^>]*>(?:\s*<[^>]*>)*\s*<a[^>]*href="[^"]*/country/(?P<country>[^"]*)"',
                              page, re.IGNORECASE)
            if match:
                info['country'] = match.group('country')

        accounts = set()
        match = re.search(r'<div[^>]*>\s*External\s*Profiles.*?</div>[^<]*</div>', page, re.DOTALL)
        if match:
            matches = re.finditer('<a[^>]*href="(?P<url>[^"]*)"[^>]*>', match.group(0))
            for match in matches:
                url = match.group('url')
                url = url.strip('/')
                _, _, host, *_, key = url.split('/')
                host = host.strip('www.')
                accounts.add((host, key))
        info['accounts'] = [{'host': host, 'key': key} for host, key in accounts]

        match = re.search('<h3[^>]*>(?P<name>[^>]*)<', page)
        info['name'] = html.unescape(match.group('name').strip())
        return info

    def get_standings(self, users=None, statistics=None, **kwargs):
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
            if (duration := infos.get('duration')):
                standings['duration_in_secs'] = parse_duration(duration).total_seconds()

        def find_related(statistics):
            infos = deepcopy(self.info.get('standings', {}).get('parse', {}))

            if self.contest.related_id is not None or not statistics:
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
                if re.search(mapping['regex'], host, re.IGNORECASE):
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
                    related = qs.first()

            if related is not None:
                self.contest.related = related
                self.contest.save()

        regex = '<table[^>]*class="[^"]*table[^"]*"[^>]*>.*?</table>'
        match = re.search(regex, page, re.DOTALL)
        html_table = match.group(0)
        table = parsed_table.ParsedTable(html_table)

        result = {}
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
            row['name'] = html.unescape(val)

            val = r.pop('Score').value.strip()
            row['solving'] = as_number(val) if val and val != '?' else 0

            for k, v in r.items():
                k = k.lower()
                if k in row:
                    continue
                v = v.value.strip()
                if not v or v == '?':
                    continue
                row[k.lower()] = as_number(v)

            if members:
                for member in members:
                    url = urljoin(standings_url, member.attrib['href'])
                    row['_profile_url'] = url
                    row['_no_update_name'] = True
                    profile_urls[url] = deepcopy(row)
            else:
                row['member'] = f"{row['name']} {self.get_season()}"
                row['info'] = {'is_team': True, '_no_profile_url': True}
                result[row['member']] = row

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
                if '_member' in row and '_info' in row and 'name' in row['_info']:
                    row['member'] = row['_member']
                    row['info'] = dict(row['_info'])
                    return row

            info = Statistic._parse_profile_page(url)
            row.setdefault('info', {}).update(info)

            row['_member'] = row['member'] = info['member']
            row['_info'] = dict(row['info'])
            return row

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

        options_parse = options.get('parse') or {}
        series = options_parse.get('series')
        if series:
            if self.contest.related_id is not None:
                self.contest.related.set_series(series)
                series = None
            self.contest.set_series(series)

        standings['result'] = result
        return standings

    @staticmethod
    def get_users_infos(users, resource, accounts, pbar=None):

        def normalize(val):
            val = val.strip()
            val = val.lower()
            val = re.sub(r'\(.*\)$', '', val)
            return val

        def is_similar_sets(a, b):
            a = set(a)
            a.discard('')
            b = set(b)
            b.discard('')

            if a.issubset(b) or b.issubset(a):
                return True

            intersection = len(a & b)
            union = len(a | b)
            iou = intersection / union
            return iou > .7

        def is_similar_names(a, b):
            a = normalize(a)
            b = normalize(b)
            if is_similar_sets(a.split(), b.split()):
                return True
            a = re.split(r'\W+', a)
            b = re.split(r'\W+', b)
            if is_similar_sets(a, b):
                return True
            return False

        def link_accounts(info, user, cphof_resource, cphof_account):
            stats = cphof_account.statistics_set.select_related('contest__related__resource')
            stats = stats.order_by('-contest__end_time')

            accounts_set = {cphof_account}

            related_accounts = info.setdefault('_related', {})
            related_accounts.update(cphof_account.info.get('_related', {}))

            def add_account(related, host, key, name=None):
                if related is None:
                    for resource in Resource.objects.filter(host__regex=host):
                        if '/' in resource.host:
                            continue
                        if '.' not in host and host not in resource.host.split('.'):
                            continue
                        break
                    else:
                        return
                else:
                    resource = related.resource

                account = resource.account_set.filter(key=key).first()
                if account is None and resource.host == 'codeforces.com':
                    profile_url = resource.profile_url.format(account=key)
                    for _ in range(3):
                        try:
                            location = REQ.geturl(profile_url)
                            if urlparse(location).path.rstrip('/'):
                                key = location.rstrip('/').split('/')[-1]
                                account = resource.account_set.filter(key__iexact=key).first()
                            break
                        except Exception as e:
                            LOG.error(f'Error on get {profile_url} = {e}')
                if account is None and related is not None and name is not None:
                    s = list(related.statistics_set.filter(place=stat.place))
                    if len(s) == 1:
                        s = s[0]
                        account = s.account
                        account_name = account.name or s.addition.get('name') or account.key
                        if not is_similar_names(account_name, name):
                            LOG.info(f'Different names in {related}: "{name}" vs "{account_name}"')
                if account is None:
                    return
                accounts_set.add(account)

            for stat in stats:
                profile_url = stat.addition['_profile_url']
                _, key = profile_url.split('/profile/', 1)
                key = unquote(key)
                host, key = key.split(':', 1)
                add_account(stat.contest.related, host, key, stat.addition.get('name'))

            for account in info['accounts']:
                add_account(None, account['host'], account['key'])

            coders_set = set()
            new_accounts = []
            for account in accounts_set:
                skip = False
                if account.resource.with_single_account():
                    for coder in account.coders.all():
                        coders_set.add(coder)
                        skip = skip or not coder.is_virtual
                if skip:
                    continue
                new_accounts.append(account)

            n_virtual = 0
            for c in coders_set:
                if c.is_virtual:
                    n_virtual += 1

            if len(coders_set) - n_virtual > 1:
                raise ExceptionParseAccounts(f'Too many coders for {user}: {coders_set}'
                                             f' ({n_virtual} of {len(coders_set)} virtual)')

            if len(coders_set) - n_virtual == 1:
                coders_set_ = set()
                for c in coders_set:
                    if c.is_virtual:
                        c.delete()
                    else:
                        coders_set_.add(c)
                coders_set = coders_set_

            if len(coders_set) == n_virtual and n_virtual > 1:
                main_account = resource.account_set.filter(key=info['member']).first()
                main_coder = main_account.coders.first() if main_account else None
                if main_coder is None:
                    raise ExceptionParseAccounts(f'Too many coders for {user}: {coders_set}')
                for c in coders_set:
                    if c != main_coder:
                        c.delete()
                coders_set = {main_coder}

            if len(coders_set) == 0:
                username = f'{settings.VIRTUAL_CODER_PREFIX_}{cphof_account.pk}'
                coder, created = Coder.objects.get_or_create(username=username, is_virtual=True)
            else:
                coder = next(iter(coders_set))

            if coder.is_virtual:
                coder.country = cphof_account.country
                coder.settings['display_name'] = cphof_account.name
                coder.save()

            if not new_accounts:
                return

            related_accounts = info.setdefault('_related', {})
            related_accounts.update(cphof_account.info.get('_related', {}))

            added_accounts = []
            for account in new_accounts:
                pk = str(account.pk)
                if related_accounts.get(pk) == coder.pk:
                    continue
                related_accounts[pk] = coder.pk
                if account.coders.filter(pk=coder.pk).exists():
                    continue
                account.coders.add(coder)
                added_accounts.append(account)

            if added_accounts:
                profile_url = cphof_resource.profile_url.format(**cphof_account.dict_with_info())
                msg = f'Account data taken from <a href="{profile_url}" class="alert-link">cphof.org</a>.'
                NotificationMessage.link_accounts(to=coder, accounts=added_accounts, message=msg)

        cphof_resource = resource
        for user, cphof_account in zip(users, accounts):
            if pbar:
                pbar.update()
            if user.startswith('university:') or cphof_account.info.get('is_team'):
                yield {'info': cphof_account.info}
                continue

            profile_url = cphof_resource.profile_url.format(**cphof_account.dict_with_info())
            try:
                info = Statistic._parse_profile_page(profile_url)
            except FailOnGetResponse as e:
                if 'page not found' in e.response.lower():
                    username = f'{settings.VIRTUAL_CODER_PREFIX_}{cphof_account.pk}'
                    yield {'delete': True, 'coder': username}
                    continue
                raise e

            with transaction.atomic():
                link_accounts(info, user, cphof_resource, cphof_account)

            ret = {'info': info}
            if cphof_account.key != info['member']:
                ret['rename'] = info['member']

            yield ret
