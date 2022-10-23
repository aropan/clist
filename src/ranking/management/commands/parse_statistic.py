#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import operator
import re
from collections import OrderedDict, defaultdict
from datetime import timedelta
from functools import lru_cache
from html import unescape
from logging import getLogger
from random import shuffle

import arrow
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone
from tqdm import tqdm
from traceback_with_variables import format_exc

from clist.models import Contest, Resource, TimingContest
from clist.templatetags.extras import (as_number, canonize, get_number_from_str, get_problem_key, get_problem_short,
                                       time_in_seconds, time_in_seconds_format)
from clist.views import update_problems, update_writers
from ranking.management.commands.common import account_update_contest_additions
from ranking.management.commands.countrier import Countrier
from ranking.management.modules.common import REQ
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.models import Account, Module, Stage, Statistics
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Parsing statistics'

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.statistic')

    def add_arguments(self, parser):
        parser.add_argument('-d', '--days', type=int, help='how previous days for update')
        parser.add_argument('-f', '--freshness_days', type=float, help='how previous days skip by modified date')
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-e', '--event', help='regex event name')
        parser.add_argument('-y', '--year', type=int, help='event year')
        parser.add_argument('-l', '--limit', type=int, help='limit count parse contest by resource', default=None)
        parser.add_argument('-c', '--no-check-timing', action='store_true', help='no check timing statistic')
        parser.add_argument('-o', '--only-new', action='store_true', default=False, help='parse without statistics')
        parser.add_argument('-s', '--stop-on-error', action='store_true', default=False, help='stop on exception')
        parser.add_argument('-u', '--users', nargs='*', default=None, help='users for parse statistics')
        parser.add_argument('-q', '--query', help='Query to filter contets')
        parser.add_argument('--random-order', action='store_true', default=False, help='Random order contests')
        parser.add_argument('--with-problems', action='store_true', default=False, help='Contests with problems')
        parser.add_argument('--no-stats', action='store_true', default=False, help='Do not pass statistics to module')
        parser.add_argument('--no-update-results', action='store_true', default=False, help='Do not update results')
        parser.add_argument('--update-without-new-rating', action='store_true', default=False, help='Update account')
        parser.add_argument('--stage', action='store_true', default=False, help='Stage contests')
        parser.add_argument('--division', action='store_true', default=False, help='Contests with divisions')
        parser.add_argument('--force-problems', action='store_true', default=False, help='Force update problems')
        parser.add_argument('--updated-before', help='Updated before date')
        parser.add_argument('-cid', '--contest-id', help='Contest id')

    def parse_statistic(
        self,
        contests,
        previous_days=None,
        freshness_days=None,
        limit=None,
        with_check=True,
        stop_on_error=False,
        random_order=False,
        no_update_results=False,
        title_regex=None,
        users=None,
        with_stats=True,
        update_without_new_rating=None,
        without_contest_filter=False,
        force_problems=False,
        contest_id=None,
        query=None,
    ):
        now = timezone.now()

        contests = contests.select_related('resource__module')

        if query:
            query = eval(query, {'Q': Q, 'F': F}, {})
            contests = contests.filter(query)

        if contest_id:
            contests = contests.filter(pk=contest_id)
        elif not without_contest_filter:
            if with_check:
                if previous_days is not None:
                    contests = contests.filter(end_time__gt=now - timedelta(days=previous_days), end_time__lt=now)
                else:
                    contests = contests.filter(Q(timing__statistic__isnull=True) | Q(timing__statistic__lt=now))
                    started = contests.filter(start_time__lt=now, end_time__gt=now, statistics__isnull=False)

                    before_end_limit_query = (
                        Q(end_time__gt=now - F('resource__module__max_delay_after_end'))
                        | Q(timing__statistic__isnull=True)
                    )
                    after_start_limit_query = Q(end_time__lt=now - F('resource__module__min_delay_after_end'))
                    long_contest_query = Q(
                        stage__isnull=True,
                        resource__module__long_contest_idle__isnull=False,
                        start_time__lt=now - F('resource__module__long_contest_idle'),
                    )
                    query = before_end_limit_query & (after_start_limit_query | long_contest_query)
                    ended = contests.filter(query)

                    contests = started.union(ended)
                    contests = contests.distinct('id')
            elif title_regex:
                contests = contests.filter(title__iregex=title_regex)
            else:
                condition = Q(end_time__lt=now - F('resource__module__min_delay_after_end')) | Q(n_statistics__gt=0)
                contests = contests.filter(condition)

        if freshness_days is not None:
            contests = contests.filter(updated__lt=now - timedelta(days=freshness_days))

        if limit:
            contests = contests.order_by('-end_time')[:limit]

        for c in contests:
            module = c.resource.module
            delay_on_success = module.delay_on_success or module.max_delay_after_end
            if now < c.end_time:
                if module.long_contest_divider:
                    delay_on_success = c.full_duration / module.long_contest_divider
                if module.long_contest_idle and c.full_duration < module.long_contest_idle:
                    delay_on_success = timedelta(minutes=1)
                if c.end_time < now + delay_on_success:
                    delay_on_success = c.end_time + module.min_delay_after_end - now
            TimingContest.objects.update_or_create(contest=c, defaults={'statistic': now + delay_on_success})

        if random_order:
            contests = list(contests)
            shuffle(contests)

        countrier = Countrier()

        def canonize_name(name):
            while True:
                v = unescape(name)
                if v == name:
                    break
                name = v
            if len(name) > 1024:
                name = name[:1020] + '...'
            return name

        count = 0
        total = 0
        n_upd_account_time = 0
        n_statistics_total = 0
        n_statistics_created = 0
        progress_bar = tqdm(contests)
        stages_ids = []
        for contest in progress_bar:
            resource = contest.resource
            if not hasattr(resource, 'module'):
                self.logger.error('Not found module contest = %s' % c)
                continue
            progress_bar.set_description(f'contest = {contest.title}')
            progress_bar.refresh()
            total += 1
            parsed = False
            user_info_has_rating = {}
            is_major_kind = resource.is_major_kind(contest.kind)
            try:
                r = {}

                if hasattr(contest, 'stage'):
                    stages_ids.append(contest.stage.pk)
                    count += 1
                    continue

                now = timezone.now()
                plugin = resource.plugin.Statistic(contest=contest)

                with REQ:
                    statistics_by_key = {} if with_stats else None
                    statistics_ids = set()
                    has_statistics = False
                    if not no_update_results and (users or users is None):
                        statistics = Statistics.objects.filter(contest=contest).select_related('account')
                        if users:
                            statistics = statistics.filter(account__key__in=users)
                        for s in tqdm(statistics.iterator(), 'getting parsed statistics'):
                            if with_stats:
                                statistics_by_key[s.account.key] = s.addition
                                has_statistics = True
                            statistics_ids.add(s.pk)
                    standings = plugin.get_standings(users=users, statistics=statistics_by_key)

                with transaction.atomic():
                    for field, attr in (
                        ('url', 'standings_url'),
                        ('contest_url', 'url'),
                        ('title', 'title'),
                        ('invisible', 'invisible'),
                        ('duration_in_secs', 'duration_in_secs'),
                    ):
                        if field in standings and standings[field] != getattr(contest, attr):
                            setattr(contest, attr, standings[field])
                            contest.save()

                    if 'options' in standings:
                        contest_options = contest.info.get('standings', {})
                        standings_options = dict(contest_options)
                        standings_options.update(standings.pop('options'))

                        canonized_fixed_fields = set([canonize(f) for f in standings_options.get('fixed_fields', [])])
                        for field in contest_options.get('fixed_fields', []):
                            canonize_field = canonize(field)
                            if canonize_field not in canonized_fixed_fields:
                                canonized_fixed_fields.add(canonize_field)
                                standings_options['fixed_fields'].append(field)

                        if canonize(standings_options) != canonize(contest_options):
                            contest.info['standings'] = standings_options
                            contest.save()

                    info_fields = standings.pop('info_fields', [])
                    info_fields += ['divisions_order', 'divisions_addition', 'advance', 'grouped_team', 'fields_values',
                                    'default_problem_full_score']
                    for field in info_fields:
                        if standings.get(field) is not None and contest.info.get(field) != standings[field]:
                            contest.info[field] = standings[field]
                            contest.save()

                    update_writers(contest, standings.pop('writers', None))

                    standings_hidden_fields = list(standings.pop('hidden_fields', []))
                    standings_hidden_fields_mapping = dict()
                    standings_hidden_fields_set = set(standings_hidden_fields)

                    standings_problems = standings.pop('problems', None)
                    if no_update_results:
                        if standings_problems:
                            standings_problems = plugin.merge_dict(standings_problems, contest.info.get('problems'))
                            update_problems(contest, standings_problems, force=force_problems)
                        count += 1
                        continue

                    result = standings.get('result', {})
                    parse_info = contest.info.get('parse', {})
                    resource_statistics = resource.info.get('statistics', {})
                    wait_rating = resource_statistics.get('wait_rating', {})
                    has_hidden = standings.pop('has_hidden', False)

                    results = []
                    if result or users is not None:
                        fields_set = set()
                        fields_types = defaultdict(set)
                        fields_preceding = defaultdict(set)
                        fields = list()
                        addition_was_ordereddict = False
                        calculate_time = False
                        n_statistics = defaultdict(int)
                        d_problems = {}
                        teams_viewed = set()
                        problems_values = defaultdict(set)
                        hidden_fields = set()
                        medals_skip = set()

                        additions = copy.deepcopy(contest.info.get('additions', {}))
                        if additions:
                            for k, v in result.items():
                                for field in [v.get('member'), v.get('name')]:
                                    v.update(OrderedDict(additions.pop(field, [])))
                            for k, v in additions.items():
                                result[k] = dict(v)

                        for r in result.values():
                            for k, v in r.items():
                                if isinstance(v, str) and chr(0x00) in v:
                                    r[k] = v.replace(chr(0x00), '')
                            r.update(parse_info.get('addition', {}))

                            account_action = r.pop('action', None)
                            if account_action == 'delete':
                                Account.objects.filter(resource=resource, key=r['member']).delete()
                                continue

                            skip_result = r.get('_no_update_n_contests')

                            def update_problems_info():
                                problems = r.get('problems', {})

                                is_new = ('team_id' not in r or r['team_id'] not in teams_viewed) and not skip_result
                                if 'team_id' in r:
                                    teams_viewed.add(r['team_id'])

                                solved = {'solving': 0}
                                if is_new:
                                    if r.get('division'):
                                        n_statistics[r.get('division')] += 1
                                    n_statistics['__total__'] += 1
                                for k, v in problems.items():
                                    if 'result' not in v:
                                        continue

                                    p = d_problems
                                    standings_p = standings_problems
                                    if standings_p and 'division' in standings_p:
                                        p = p.setdefault(r['division'], {})
                                        standings_p = standings_p.get(r['division'], [])
                                    p = p.setdefault(k, {})

                                    result_str = str(v['result'])
                                    is_accepted = result_str.startswith('+')
                                    is_hidden = result_str.startswith('?')
                                    is_score = result_str and result_str[0].isdigit()

                                    scored = is_accepted
                                    try:
                                        scored = scored or float(v['result']) > 0
                                    except Exception:
                                        pass

                                    default_full_score = (
                                        contest.info.get('default_problem_full_score')
                                        or resource.info.get('statistics', {}).get('default_problem_full_score')
                                    )
                                    if default_full_score and is_score:
                                        v_result = as_number(v['result'])
                                        if default_full_score == 'max':
                                            p['max_score'] = max(p.get('max_score', float('-inf')), v_result)
                                        elif default_full_score == 'min':
                                            p['min_score'] = min(p.get('min_score', float('inf')), v_result)
                                        else:
                                            if 'full_score' not in p:
                                                for i in standings_p:
                                                    if get_problem_key(i) == k and 'full_score' in i:
                                                        p['full_score'] = i['full_score']
                                                        break
                                                else:
                                                    p['full_score'] = default_full_score
                                            if 'partial' not in v and p['full_score'] - v_result > 1e-9:
                                                v['partial'] = True
                                            if not v.get('partial'):
                                                solved['solving'] += 1
                                    ac = scored and not v.get('partial', False)

                                    if contest.info.get('with_last_submit_time') and scored:
                                        if '_last_submit_time' not in r or r['_last_submit_time'] < v['time']:
                                            r['_last_submit_time'] = v['time']
                                    if contest.info.get('without_problem_first_ac'):
                                        v.pop('first_ac', None)
                                        v.pop('first_ac_of_all', None)
                                    if contest.info.get('without_problem_time'):
                                        v.pop('time', None)

                                    if r.get('_skip_for_problem_stat') or skip_result:
                                        continue

                                    if ac and v.get('time'):
                                        if contest.info.get('with_time_from_timeline') and 'time_in_seconds' not in v:
                                            timeline = resource.info.get('standings', {}).get('timeline', {})
                                            if timeline:
                                                v['time_in_seconds'] = time_in_seconds(timeline, v['time'])

                                        if v.get('first_ac') or v.get('first_ac_of_all'):
                                            first_ac = p.setdefault('first_ac', {})
                                            first_ac['in_seconds'] = -1
                                            first_ac['time'] = v['time']
                                            first_ac['accounts'] = [r['member']]
                                        elif 'time_in_seconds' in v:
                                            in_seconds = v['time_in_seconds']
                                            first_ac = p.setdefault('first_ac', {})
                                            delta = in_seconds - first_ac.get('in_seconds', -1)
                                            if 'in_seconds' in first_ac and abs(delta) < 1e-9:
                                                first_ac['accounts'].append(r['member'])
                                            if 'in_seconds' not in first_ac or delta < 0:
                                                first_ac['in_seconds'] = in_seconds
                                                first_ac['time'] = v['time']
                                                first_ac['accounts'] = [r['member']]

                                    if not is_new:
                                        continue

                                    p['n_teams'] = p.get('n_teams', 0) + 1
                                    if ac:
                                        p['n_accepted'] = p.get('n_accepted', 0) + 1
                                    elif scored and v.get('partial'):
                                        p['n_partial'] = p.get('n_partial', 0) + 1
                                    elif is_hidden:
                                        p['n_hidden'] = p.get('n_hidden', 0) + 1

                                if 'default_problem_full_score' in contest.info and solved and 'solved' not in r:
                                    r['solved'] = solved

                            default_division = contest.info.get('default_division')
                            if default_division and 'division' not in r:
                                r['division'] = default_division

                            update_problems_info()

                            results.append(r)

                        members = [r['member'] for r in results]
                        accounts = resource.account_set.filter(key__in=members)
                        accounts = {a.key: a for a in accounts}

                        for r in tqdm(results, desc=f'update results {contest}'):
                            member = r.pop('member')
                            skip_result = r.get('_no_update_n_contests')

                            account_created = member not in accounts
                            if account_created:
                                account = Account.objects.create(resource=resource, key=member)
                                accounts[member] = account
                            else:
                                account = accounts[member]

                            stats = (statistics_by_key or {}).get(member, {})

                            def update_addition_fields():
                                addition_fields = parse_info.get('addition_fields', [])
                                if not stats or not addition_fields:
                                    return
                                for d in addition_fields:
                                    k = d['out']
                                    value = r.get(d['field'])
                                    pvalue = stats.get(d.get('vs_field', k))

                                    on_update_value = d.get('on_update_value')
                                    if on_update_value == 'now':
                                        fields_types[k].add('timestamp')
                                    elif on_update_value:
                                        raise ValueError(f'Unkonwn value = {on_update_value} in addition field = {d}')

                                    if d.get('skip_after_end') and contest.end_time < now:
                                        value = stats.get(k)
                                        if value is not None:
                                            r[k] = value
                                        continue

                                    upd = False
                                    if pvalue is not None:
                                        cmp = d.get('comparator')
                                        if value is None or cmp and getattr(operator, cmp)(pvalue, value):
                                            value = pvalue
                                            upd = True
                                            if on_update_value == 'now':
                                                value = int(now.timestamp())
                                    if d.get('on_update') and not upd:
                                        value = stats.get(k)
                                    if value is not None:
                                        r[k] = value

                            def update_account_time():
                                if (
                                    contest.info.get('_no_update_account_time') or
                                    skip_result or
                                    contest.end_time > now
                                ):
                                    return

                                nonlocal n_upd_account_time
                                no_rating = with_stats and (
                                    ('new_rating' in stats) + ('rating_change' in stats) + ('old_rating' in stats) < 2
                                )

                                updated_delta = resource_statistics.get('account_updated_delta', {'days': 1})
                                updated = now + timedelta(**updated_delta)

                                title_re = wait_rating.get('title_re')
                                if title_re and not re.search(title_re, contest.title):
                                    return

                                has_coder = wait_rating.get('has_coder')
                                top_rank_percent = wait_rating.get('top_rank_percent')
                                assert bool(has_coder is None) == bool(top_rank_percent is None)
                                if has_coder and top_rank_percent:
                                    rank = get_number_from_str(r.get('place'))
                                    n_top_rank = len(result) * top_rank_percent
                                    if (rank is None or rank > n_top_rank) and not account.coders.exists():
                                        return

                                if no_rating and wait_rating:
                                    updated = now + timedelta(minutes=10)

                                if updated > account.updated:
                                    return

                                update_on_parsed_time = (
                                    (contest.parsed_time is None or contest.parsed_time < contest.end_time)
                                    and now < contest.end_time + timedelta(days=1)
                                )

                                wait_days = wait_rating.get('days')
                                if no_rating and wait_rating and contest.end_time + timedelta(days=wait_days) > now:
                                    division = r.get('division')
                                    if division not in user_info_has_rating:
                                        generator = plugin.get_users_infos([member], resource, [account])
                                        try:
                                            user_info = next(generator)
                                            params = user_info.get('contest_addition_update_params', {})
                                            field = user_info.get('contest_addition_update_by') or params.get('by') or 'key'  # noqa
                                            updates = user_info.get('contest_addition_update') or params.get('update') or {}  # noqa
                                            if not isinstance(field, (list, tuple)):
                                                field = [field]
                                            user_info_has_rating[division] = False
                                            for f in field:
                                                if getattr(contest, f) in updates:
                                                    user_info_has_rating[division] = True
                                                    break
                                        except Exception:
                                            self.logger.error(format_exc())
                                            user_info_has_rating[division] = False

                                    if user_info_has_rating[division]:
                                        n_upd_account_time += 1
                                        account.updated = updated
                                        account.save()
                                elif (
                                    account_created
                                    or not has_statistics
                                    or update_on_parsed_time
                                    or (update_without_new_rating and no_rating)
                                ):
                                    n_upd_account_time += 1
                                    account.updated = updated
                                    account.save()

                            def update_account_info():
                                if contest.info.get('_push_name_instead_key'):
                                    r['_name_instead_key'] = True
                                if contest.info.get('_push_name_instead_key_to_account'):
                                    account.info['_name_instead_key'] = True
                                    account.save()

                                no_update_name = r.pop('_no_update_name', False)
                                field_update_name = r.pop('_field_update_name', 'name')
                                if r.get(field_update_name) and 'team_id' not in r:
                                    r[field_update_name] = canonize_name(r[field_update_name])
                                    if (
                                        not no_update_name and
                                        account.name != r[field_update_name] and
                                        account.key != r[field_update_name]
                                    ):
                                        account.name = r[field_update_name]
                                        account.save()

                                country = r.get('country', None)
                                if country:
                                    country = countrier.get(country)
                                    if country and country != account.country:
                                        account.country = country
                                        account.save()

                                contest_addition_update = r.pop('contest_addition_update', {})
                                if contest_addition_update:
                                    account_update_contest_additions(
                                        account,
                                        contest_addition_update,
                                        timedelta(days=31) if with_check else None
                                    )

                                account_info = r.pop('info', {})
                                if account_info:
                                    if 'rating' in account_info:
                                        if is_major_kind:
                                            account_info['_rating_time'] = int(now.timestamp())
                                        else:
                                            account_info.pop('rating')
                                    if 'name' in account_info:
                                        name = account_info.pop('name')
                                        account.name = name if name and name != account.key else None

                                    account.info.update(account_info)
                                    account.save()

                            def update_stat_info():
                                problems = r.get('problems', {})

                                for field, out in (
                                    ('language', '_languages'),
                                    ('verdict', '_verdicts'),
                                ):
                                    values = set()
                                    for problem in problems.values():
                                        value = problem.get(field)
                                        if value:
                                            problems_values[out].add(value)
                                            values.add(value)
                                    if out not in r and values:
                                        r[out] = list(values)

                                advance = contest.info.get('advance')
                                if advance:
                                    k = 'advanced'
                                    r.pop(k, None)
                                    for cond in advance['filter']:
                                        field = cond['field']
                                        value = r.get(field)
                                        value = get_number_from_str(value)
                                        if value is None:
                                            continue
                                        r[k] = getattr(operator, cond['operator'])(value, cond['threshold'])

                                medals = contest.info.get('standings', {}).get('medals')
                                if medals and contest.end_time < now:
                                    k = 'medal'
                                    r.pop(k, None)
                                    if 'place' in r:
                                        place = get_number_from_str(r['place'])
                                        if member in contest.info.get('standings', {}).get('medals_skip', []):
                                            medals_skip.add(member)
                                        elif place:
                                            place -= len(medals_skip)
                                            for medal in medals:
                                                if place <= medal['count']:
                                                    r[k] = medal['name']
                                                    if 'field' in medal:
                                                        r[medal['field']] = medal['value']
                                                        r[f'_{k}_title_field'] = medal['field']
                                                    break
                                                place -= medal['count']
                                    medal_fields = [m['field'] for m in medals if 'field' in m] or [k]
                                    for f in medal_fields:
                                        if f not in fields_set:
                                            fields_set.add(f)
                                            fields.append(f)

                                if 'is_rated' in r and not r['is_rated']:
                                    r.pop('old_rating', None)
                                    r.pop('rating_change', None)
                                    r.pop('new_rating', None)

                            def update_problems_first_ac():
                                problems = r.get('problems', {})

                                for k, v in problems.items():
                                    p = d_problems
                                    if standings_problems and 'division' in standings_problems:
                                        p = p.setdefault(r['division'], {})
                                    p = p.setdefault(k, {})
                                    if 'first_ac' not in p:
                                        continue

                                    if member in p['first_ac']['accounts']:
                                        v['first_ac'] = True

                            def get_addition():
                                defaults = {
                                    'place': r.pop('place', None),
                                    'solving': r.pop('solving', 0),
                                    'upsolving': r.pop('upsolving', 0),
                                }
                                defaults = {k: v for k, v in defaults.items() if v != '__unchanged__'}

                                addition = type(r)()
                                nonlocal addition_was_ordereddict
                                addition_was_ordereddict |= isinstance(addition, OrderedDict)
                                previous_fields = set()
                                for k, v in r.items():
                                    orig_k = k
                                    is_hidden_field = orig_k in standings_hidden_fields_set
                                    if k[0].isalpha() and not re.match('^[A-Z]+([0-9]+)?$', k):
                                        k = k[0].upper() + k[1:]
                                        k = '_'.join(map(str.lower, re.findall('([A-ZА-Я]+[^A-ZА-Я]+|[A-ZА-Я]+$)', k)))

                                    if is_hidden_field:
                                        standings_hidden_fields_mapping[orig_k] = k
                                        hidden_fields.add(k)
                                    if k not in fields_set:
                                        fields_set.add(k)
                                        fields.append(k)
                                    fields_preceding[k] |= previous_fields
                                    previous_fields.add(k)

                                    if (k in Resource.RATING_FIELDS or k == 'rating_change') and v is None:
                                        continue

                                    fields_types[k].add(type(v).__name__)
                                    addition[k] = v

                                if (
                                    addition.get('rating_change') is None
                                    and addition.get('new_rating') is not None
                                    and addition.get('old_rating') is not None
                                ):
                                    delta = addition['new_rating'] - addition['old_rating']
                                    f = 'rating_change'
                                    v = f'{"+" if delta > 0 else ""}{delta}'
                                    fields_types[f].add(type(v).__name__)
                                    addition[f] = v
                                    if f not in fields_set:
                                        fields_set.add(f)
                                        fields.append(f)
                                    fields_preceding[f] |= previous_fields

                                rating_time = int(min(contest.end_time, now).timestamp())
                                if (
                                    is_major_kind
                                    and 'new_rating' in addition
                                    and ('rating' not in account.info
                                         or account.info.get('_rating_time', -1) <= rating_time)
                                ):
                                    account.info['_rating_time'] = rating_time
                                    account.info['rating'] = addition['new_rating']
                                    account.save()

                                try_calculate_time = contest.calculate_time or (
                                    contest.start_time <= now < contest.end_time and
                                    not resource.info.get('parse', {}).get('no_calculate_time', False) and
                                    resource.module.long_contest_idle and
                                    contest.full_duration < resource.module.long_contest_idle and
                                    'penalty' in fields_set
                                )

                                if not try_calculate_time:
                                    defaults['addition'] = addition

                                return defaults, addition, try_calculate_time

                            def update_after_update_or_create(statistic, created, try_calculate_time):
                                problems = r.get('problems', {})

                                if not created:
                                    nonlocal calculate_time
                                    if statistics_ids:
                                        statistics_ids.remove(statistic.pk)

                                    if try_calculate_time:
                                        p_problems = statistic.addition.get('problems', {})

                                        ts = int((now - contest.start_time).total_seconds())
                                        ts = min(ts, contest.duration_in_secs)
                                        timeline = resource.info.get('standings', {}).get('timeline', {})
                                        time = time_in_seconds_format(timeline, ts, num=2)

                                        for k, v in problems.items():
                                            v_result = v.get('result', '')
                                            if isinstance(v_result, str) and '?' in v_result:
                                                calculate_time = True
                                            p = p_problems.get(k, {})
                                            if 'time' in v:
                                                continue
                                            has_change = v.get('result') != p.get('result')
                                            if (not has_change or contest.end_time < now) and 'time' in p:
                                                v['time'] = p['time']
                                            else:
                                                v['time'] = time

                                for p in problems.values():
                                    p_result = p.get('result', '')
                                    if isinstance(p_result, str) and '?' in p_result:
                                        nonlocal has_hidden
                                        has_hidden = True

                                if try_calculate_time:
                                    statistic.addition = addition
                                    statistic.save()

                            update_addition_fields()
                            update_account_time()
                            update_account_info()
                            update_stat_info()
                            if users is None:
                                update_problems_first_ac()
                            defaults, addition, try_calculate_time = get_addition()

                            statistic, statistics_created = Statistics.objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )
                            n_statistics_total += 1
                            n_statistics_created += statistics_created

                            update_after_update_or_create(statistic, statistics_created, try_calculate_time)

                        if users is None:
                            if has_hidden != contest.has_hidden_results:
                                contest.has_hidden_results = has_hidden
                                contest.save()

                            for field, values in problems_values.items():
                                if values:
                                    field = field.strip('_')
                                    values = list(sorted(values))
                                    if canonize(values) != canonize(contest.info.get(field)):
                                        contest.info[field] = values
                                    if field not in hidden_fields:
                                        standings_hidden_fields.append(field)
                                        hidden_fields.add(field)

                            if fields_set and not addition_was_ordereddict:
                                fields.sort()
                            for rating_field in ('old_rating', 'rating_change', 'new_rating'):
                                if rating_field in fields_set:
                                    fields.remove(rating_field)
                                    fields.append(rating_field)

                            if statistics_ids:
                                first = Statistics.objects.filter(pk__in=statistics_ids).first()
                                if first:
                                    self.logger.info(f'First deleted: {first}, account = {first.account}')
                                delete_info = Statistics.objects.filter(pk__in=statistics_ids).delete()
                                self.logger.info(f'Delete info: {delete_info}')
                                progress_bar.set_postfix(deleted=str(delete_info))

                            for f in fields_preceding.keys():
                                fields.remove(f)
                            while fields_preceding:
                                k = None
                                for f, v in fields_preceding.items():
                                    if k is None or (len(v) < len(fields_preceding[k])):
                                        k = f
                                fields.append(k)
                                fields_preceding.pop(k)
                                for f, v in fields_preceding.items():
                                    v.discard(k)

                            if canonize(fields) != canonize(contest.info.get('fields')):
                                contest.info['fields'] = fields

                            standings_hidden_fields = [standings_hidden_fields_mapping.get(f, f)
                                                       for f in standings_hidden_fields]
                            hidden_fields = [field for field in standings_hidden_fields if field in hidden_fields]
                            if canonize(hidden_fields) != canonize(contest.info.get('hidden_fields')):
                                contest.info['hidden_fields'] = hidden_fields

                            fields_types = {k: list(v) for k, v in fields_types.items()}
                            for k, v in standings.get('fields_types', {}).items():
                                fields_types.setdefault(k, []).extend(v)
                            contest.info['fields_types'] = fields_types

                            if calculate_time and not contest.calculate_time:
                                contest.calculate_time = True

                            contest.n_statistics = n_statistics.pop('__total__', 0)
                            contest.parsed_time = now

                            if standings_problems is not None:
                                problems_ratings = {}
                                problems = contest.info.get('problems', [])
                                if 'division' in problems:
                                    problems = sum(problems['division'].values(), [])
                                for problem in problems:
                                    if 'rating' in problem:
                                        problems_ratings[get_problem_key(problem)] = problem['rating']

                                if 'division' in standings_problems:
                                    for d, ps in standings_problems['division'].items():
                                        for p in ps:
                                            key = get_problem_key(p)
                                            short = get_problem_short(p)
                                            if not short:
                                                continue
                                            p.update(d_problems.get(d, {}).get(short, {}))
                                            p['n_total'] = n_statistics[d]
                                            if key in problems_ratings:
                                                p['rating'] = problems_ratings[key]
                                    if isinstance(standings_problems['division'], OrderedDict):
                                        divisions_order = list(standings_problems['division'].keys())
                                        standings_problems['divisions_order'] = divisions_order
                                    standings_problems['n_statistics'] = n_statistics
                                else:
                                    for p in standings_problems:
                                        key = get_problem_key(p)
                                        short = get_problem_short(p)
                                        if not short:
                                            continue
                                        p.update(d_problems.get(short, {}))
                                        p['n_total'] = contest.n_statistics
                                        if key in problems_ratings:
                                            p['rating'] = problems_ratings[key]

                                update_problems(contest, problems=standings_problems, force=force_problems)
                            contest.save()
                            if resource.has_problem_rating and contest.end_time < now:
                                call_command('calculate_problem_rating', contest=contest.pk, force=force_problems)
                            progress_bar.set_postfix(n_fields=len(fields))
                    else:
                        if standings_problems is not None and standings_problems:
                            standings_problems = plugin.merge_dict(standings_problems, contest.info.get('problems'))
                            update_problems(contest, problems=standings_problems, force=force_problems or not users)

                    timing_delta = standings.get('timing_statistic_delta')
                    if now < contest.end_time:
                        timing_delta = parse_info.get('timing_statistic_delta', timing_delta)
                    if has_hidden and contest.end_time < now < contest.end_time + timedelta(days=1):
                        timing_delta = timing_delta or timedelta(minutes=10)
                    if wait_rating and not has_statistics and results and 'days' in wait_rating:
                        timing_delta = timing_delta or timedelta(days=wait_rating['days']) / 10
                    timing_delta = timedelta(**timing_delta) if isinstance(timing_delta, dict) else timing_delta
                    if timing_delta is not None:
                        self.logger.info(f'Statistic timing delta = {timing_delta}')
                        next_timing_statistic = timezone.now() + timing_delta
                        if next_timing_statistic < contest.timing.statistic:
                            contest.timing.statistic = next_timing_statistic
                            contest.timing.save()
                        contest.info['_timing_statistic_delta_seconds'] = timing_delta.total_seconds()
                    else:
                        contest.info.pop('_timing_statistic_delta_seconds', None)
                    contest.save()

                    action = standings.get('action')
                    if action is not None:
                        args = []
                        if isinstance(action, tuple):
                            action, *args = action
                        self.logger.info(f'Action {action} with {args}, contest = {contest}, url = {contest.url}')
                        if action == 'delete':
                            force = standings.get('force')
                            if not force and Statistics.objects.filter(contest=contest).exists():
                                self.logger.info('No deleted. Contest have statistics')
                            elif not force and now < contest.end_time:
                                self.logger.info(f'No deleted. Try after = {contest.end_time - now}')
                            else:
                                delete_info = contest.delete()
                                self.logger.info(f'Delete info contest: {delete_info}')
                        elif action == 'url':
                            contest.url = args[0]
                            contest.save()
                if 'result' in standings:
                    count += 1
                parsed = True
            except (ExceptionParseStandings, InitModuleException) as e:
                progress_bar.set_postfix(exception=str(e), cid=str(contest.pk))
            except Exception as e:
                self.logger.error(f'contest = {contest.pk}, error = {e}, row = {r}')
                self.logger.error(format_exc())
                if stop_on_error:
                    break
            if not parsed:
                if (
                    contest.n_statistics and
                    now < contest.end_time and
                    resource.module.long_contest_idle and
                    contest.full_duration < resource.module.long_contest_idle
                ):
                    delay = timedelta(minutes=1)
                elif contest.n_statistics and now < contest.end_time and resource.module.long_contest_divider:
                    delay = contest.full_duration / (resource.module.long_contest_divider ** 2)
                else:
                    delay = resource.module.delay_on_error
                if now < contest.end_time < now + delay:
                    delay = contest.end_time + resource.module.min_delay_after_end - now

                if '_timing_statistic_delta_seconds' in contest.info:
                    timing_delta = timedelta(seconds=contest.info['_timing_statistic_delta_seconds'])
                    if resource.module.long_contest_divider:
                        timing_delta /= resource.module.long_contest_divider
                    delay = min(delay, timing_delta)

                contest.timing.statistic = timezone.now() + delay
                contest.timing.save()
            elif not no_update_results and (users is None or users):
                stages = Stage.objects.filter(
                    ~Q(pk__in=stages_ids),
                    contest__start_time__lte=contest.start_time,
                    contest__end_time__gte=contest.end_time,
                    contest__resource=resource,
                )
                for stage in stages:
                    if Contest.objects.filter(pk=contest.pk, **stage.filter_params).exists():
                        stages_ids.append(stage.pk)

        @lru_cache(maxsize=None)
        def update_stage(stage):
            exclude_stages = stage.score_params.get('advances', {}).get('exclude_stages', [])
            ret = stage.pk in stages_ids
            for s in Stage.objects.filter(pk__in=exclude_stages):
                if update_stage(s):
                    ret = True
            if ret:
                stage.update()
            return ret

        for stage in tqdm(Stage.objects.filter(pk__in=stages_ids), total=len(stages_ids), desc='getting stages'):
            update_stage(stage)

        progress_bar.close()
        self.logger.info(f'Parsed statistic: {count} of {total}')
        self.logger.info(f'Number of updated account time: {n_upd_account_time}')
        self.logger.info(f'Number of created statistics: {n_statistics_created} of {n_statistics_total}')
        return count, total

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            if len(args.resources) == 1:
                contests = Contest.objects.filter(resource__module__resource__host__iregex=args.resources[0])
            else:
                resources = [Resource.objects.get(host__iregex=r) for r in args.resources]
                contests = Contest.objects.filter(resource__module__resource__host__in=resources)
        else:
            has_module = Module.objects.filter(resource_id=OuterRef('resource__pk'))
            contests = Contest.objects.annotate(has_module=Exists(has_module)).filter(has_module=True)

        if args.only_new:
            has_statistics = Statistics.objects.filter(contest_id=OuterRef('pk'))
            contests = contests.annotate(has_statistics=Exists(has_statistics)).filter(has_statistics=False)

        if args.year:
            contests = contests.filter(start_time__year=args.year)

        if args.stage:
            contests = contests.filter(stage__isnull=False)

        if args.division:
            contests = contests.filter(info__problems__division__isnull=False)

        if args.with_problems:
            contests = contests.exclude(problem_set=None)

        if args.updated_before:
            contests = contests.filter(updated__lt=arrow.get(args.updated_before).datetime)

        self.parse_statistic(
            contests=contests,
            previous_days=args.days,
            limit=args.limit,
            with_check=not args.no_check_timing,
            stop_on_error=args.stop_on_error,
            random_order=args.random_order,
            no_update_results=args.no_update_results,
            freshness_days=args.freshness_days,
            title_regex=args.event,
            users=args.users,
            with_stats=not args.no_stats,
            update_without_new_rating=args.update_without_new_rating,
            force_problems=args.force_problems,
            contest_id=args.contest_id,
            query=args.query,
        )
