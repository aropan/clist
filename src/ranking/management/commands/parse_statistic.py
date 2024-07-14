#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import logging
import operator
import os
import re
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html import unescape
from math import isclose
from random import shuffle

import arrow
import humanize
import tqdm as _tqdm
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils.timezone import now as timezone_now
from django_print_sql import print_sql_decorator

from submissions.models import Language, Submission, Testing, Verdict

from clist.models import Contest, Problem, Resource
from clist.templatetags.extras import (as_number, canonize, get_item, get_number_from_str, get_problem_key,
                                       get_problem_short, is_solved, normalize_field, time_in_seconds,
                                       time_in_seconds_format)
from clist.views import update_problems, update_writers
from logify.models import EventLog, EventStatus
from notification.models import NotificationMessage, Subscription
from pyclist.decorators import analyze_db_queries
from ranking.management.commands.parse_accounts_infos import rename_account
from ranking.management.modules.common import REQ, UNCHANGED, ProxyLimitReached
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.models import Account, AccountRenaming, Module, Stage, Statistics
from ranking.utils import account_update_contest_additions
from ranking.views import update_standings_socket
from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.countrier import Countrier
from utils.logger import suppress_db_logging_context
from utils.timetools import parse_datetime
from utils.traceback_with_vars import colored_format_exc

EPS = 1e-9


class ChannelLayerHandler(logging.Handler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.channel_layer = get_channel_layer()
        self.group_name = None
        self.capacity = 0
        self.states = None

    def emit(self, record):
        if not self.group_name or not self.capacity:
            return
        log_entry = self.format(record)
        self.send_message(log_entry)

    def send_done(self, done=False):
        if not self.group_name:
            return
        self.send_message('DONE' if done else 'FAILED', done=done)
        self.group_name = None

    def send_message(self, message, **kwargs):
        context = {'type': 'update_statistics', 'line': message}
        context.update(kwargs)
        async_to_sync(self.channel_layer.group_send)(self.group_name, context)
        self.decrease_capacity()

    def send_progress(self, progress_bar: _tqdm.tqdm):
        if not self.group_name or not self.capacity:
            return
        if not progress_bar.n or not progress_bar.total:
            return

        n = min(progress_bar.n, progress_bar.total)
        total = progress_bar.total
        desc = progress_bar.desc
        state = (n, total)

        if desc not in self.states:
            if n < total:
                self.states[desc] = state
            return
        if self.states[desc] == state:
            return

        if n == total:
            self.states.pop(desc)
        else:
            self.states[desc] = state

        rate = progress_bar.format_dict['rate']
        estimate_time = (total - n) / rate if rate else None
        estimate_time_str = f'{humanize.naturaldelta(timedelta(seconds=estimate_time))}' if estimate_time else '…'
        percentage = n / total
        context = {
            'type': 'update_statistics',
            'progress': percentage,
            'desc': f'{desc} ({percentage * 100:.2f}%, {estimate_time_str})',
        }
        async_to_sync(self.channel_layer.group_send)(self.group_name, context)
        self.decrease_capacity()

    def decrease_capacity(self):
        self.capacity -= 1
        if self.capacity == 0:
            context = {'type': 'update_statistics', 'line': 'REACH_LOGGING_LIMIT'}
            async_to_sync(self.channel_layer.group_send)(self.group_name, context)

    def set_contest(self, contest):
        self.group_name = contest.channel_update_statistics_group_name
        self.capacity = settings.CHANNEL_LAYERS_CAPACITY - 10
        self.states = {}

    def __del__(self):
        self.send_done()


class tqdm(_tqdm.tqdm):
    _channel_layer_handler = None

    def __init__(self, *args, **kwargs):
        kwargs['mininterval'] = 0.2
        super().__init__(*args, **kwargs)

    def __iter__(self):
        for obj in super().__iter__():
            yield obj
            self._channel_layer_handler.send_progress(self)
        self._channel_layer_handler.send_progress(self)

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._channel_layer_handler.send_progress(self)

    def close(self, *args, **kwargs):
        super().close(*args, **kwargs)
        self._channel_layer_handler.send_progress(self)


def canonize_name(name):
    while True:
        v = unescape(name)
        if v == name:
            break
        name = v
    if len(name) > 1024:
        name = name[:1020] + '...'
    return name


class Command(BaseCommand):
    help = 'Parsing statistics'

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.logger = logging.getLogger('ranking.parse.statistic')

    def add_arguments(self, parser):
        parser.add_argument('-d', '--days', type=int, help='how previous days for update')
        parser.add_argument('-f', '--freshness_days', type=float, help='how previous days skip by modified date')
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-e', '--event', help='regex event name')
        parser.add_argument('-y', '--year', type=int, help='event year')
        parser.add_argument('-l', '--limit', type=int, help='limit count parse contest by resource', default=None)
        parser.add_argument('-lo', '--limit-order', type=str, help='order for limit count', default=None)
        parser.add_argument('-c', '--no-check-timing', action='store_true', help='no check timing statistic')
        parser.add_argument('-o', '--only-new', action='store_true', default=False, help='parse without statistics')
        parser.add_argument('-s', '--stop-on-error', action='store_true', default=False, help='stop on exception')
        parser.add_argument('-u', '--users', nargs='*', default=None, help='users for parse statistics')
        parser.add_argument('-q', '--query', help='Query to filter contets')
        parser.add_argument('--reparse', action='store_true', default=False, help='Reparse statistics')
        parser.add_argument('--random-order', action='store_true', default=False, help='Random order contests')
        parser.add_argument('--with-problems', action='store_true', default=False, help='Contests with problems')
        parser.add_argument('--no-stats', action='store_true', default=False, help='Do not pass statistics to module')
        parser.add_argument('--no-update-results', action='store_true', default=False, help='Do not update results')
        parser.add_argument('--update-without-new-rating', action='store_true', default=False, help='Update account')
        parser.add_argument('--stage', action='store_true', default=False, help='Stage contests')
        parser.add_argument('--division', action='store_true', default=False, help='Contests with divisions')
        parser.add_argument('--force-problems', action='store_true', default=False, help='Force update problems')
        parser.add_argument('--updated-before', help='Updated before date')
        parser.add_argument('--force-socket', action='store_true', default=False, help='Force update socket')
        parser.add_argument('--without-n_statistics', action='store_true', default=False, help='Force update')
        parser.add_argument('--before-date', default=False, help='Update contests that have been updated to date')
        parser.add_argument('--after-date', default=False, help='Update contests that have been updated after date')
        parser.add_argument('--with-medals', action='store_true', default=False, help='Contest with medals')
        parser.add_argument('--without-fill-coder-problems', action='store_true', default=False)
        parser.add_argument('--without-calculate-problem-rating', action='store_true', default=False)
        parser.add_argument('--without-calculate-rating-prediction', action='store_true', default=False)
        parser.add_argument('--without-stage', action='store_true', default=False, help='Without update stage contests')
        parser.add_argument('--contest-id', '-cid', help='Contest id')
        parser.add_argument('--no-update-problems', action='store_true', default=False, help='No update problems')
        parser.add_argument('--is-rated', action='store_true', default=False, help='Contest is rated')
        parser.add_argument('--after', type=str, help='Events after date')
        parser.add_argument('--for-account', type=str, help='Events for account')
        parser.add_argument('--ignore-stage', action='store_true', default=False, help='Ignore stage')

    def parse_statistic(
        self,
        contests,
        previous_days=None,
        freshness_days=None,
        before_date=None,
        after_date=None,
        limit=None,
        limit_order=None,
        with_check=True,
        stop_on_error=False,
        random_order=False,
        no_update_results=False,
        title_regex=None,
        users=None,
        with_stats=True,
        update_without_new_rating=None,
        force_problems=False,
        force_socket=False,
        without_n_statistics=False,
        contest_id=None,
        query=None,
        without_fill_coder_problems=False,
        without_calculate_problem_rating=False,
        without_calculate_rating_prediction=False,
        without_stage=False,
        no_update_problems=None,
        is_rated=None,
        for_account=None,
        ignore_stage=None,
    ):
        channel_layer_handler = ChannelLayerHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%b-%d %H:%M:%S')
        channel_layer_handler.setFormatter(formatter)
        channel_layer_handler.setLevel(logging.INFO)
        root_logger = logging.getLogger()
        root_logger.addHandler(channel_layer_handler)

        tqdm._channel_layer_handler = channel_layer_handler
        _tqdm.tqdm = tqdm

        now = timezone_now()

        contests = contests.select_related('resource__module')

        if query:
            query = eval(query, {'Q': Q, 'F': F}, {})
            contests = contests.filter(query)

        if contest_id:
            if ',' in str(contest_id):
                contest_id = contest_id.split(',')
                contests = contests.filter(pk__in=contest_id)
            else:
                contests = contests.filter(pk=contest_id)
        else:
            if with_check:
                if previous_days is not None:
                    contests = contests.filter(end_time__gt=now - timedelta(days=previous_days), end_time__lt=now)
                else:
                    contests = contests.filter(Q(statistic_timing=None) | Q(statistic_timing__lt=now))
                    parsed_contests = contests.filter(start_time__lt=now, end_time__gt=now, statistics__isnull=False)

                    before_end_limit_query = (
                        Q(end_time__gt=now - F('resource__module__max_delay_after_end'))
                        | Q(statistic_timing=None)
                    )

                    after_start_limit_query = Q(
                        resource__module__min_delay_after_end__isnull=False,
                        end_time__lt=now - F('resource__module__min_delay_after_end'),
                    )
                    start_limit = now - (F('end_time') - F('start_time')) / F('resource__module__long_contest_divider')
                    after_start_divider_query = Q(
                        resource__module__min_delay_after_end__isnull=True,
                        resource__module__long_contest_divider__isnull=False,
                        start_time__lt=start_limit,
                    )
                    long_contest_query = Q(
                        resource__module__long_contest_idle__isnull=False,
                        start_time__lt=now - F('resource__module__long_contest_idle'),
                    )
                    after_start_query = after_start_limit_query | after_start_divider_query | long_contest_query

                    query = before_end_limit_query & after_start_query
                    in_range_contests = contests.filter(query)

                    contests = Contest.objects.filter(Q(pk__in=parsed_contests) | Q(pk__in=in_range_contests))
                    contests = contests.filter(stage__isnull=True)
                contests = contests.filter(resource__module__enable=True)
            else:
                contests = contests.filter(start_time__lt=now)
            if title_regex:
                contests = contests.filter(title__iregex=title_regex)
            if without_n_statistics:
                contests = contests.filter(Q(n_statistics__isnull=True) | Q(n_statistics__lte=0))

        if freshness_days is not None:
            contests = contests.filter(updated__lt=now - timedelta(days=freshness_days))
        if before_date:
            before_date = parse_datetime(before_date)
            contests = contests.filter(Q(parsed_time__isnull=True) | Q(parsed_time__lt=before_date))
        if after_date:
            after_date = parse_datetime(after_date)
            contests = contests.filter(Q(parsed_time__isnull=True) | Q(parsed_time__gt=after_date))
        if is_rated:
            contests = contests.filter(is_rated=True)
        if for_account:
            contests = contests.filter(statistics__account__key=for_account)

        if limit:
            contests = contests.order_by(limit_order or '-end_time', '-id')[:limit]

        contests = list(contests)

        if random_order:
            shuffle(contests)
        else:
            contests.sort(key=lambda contest: contest.start_time)

        countrier = Countrier()

        has_error = False
        count = 0
        total = 0
        n_contest_progress = 0
        n_account_time_update = 0
        n_statistics_total = 0
        n_statistics_created = 0
        n_calculated_rating_prediction = 0
        n_calculated_problem_rating = 0
        progress_bar = tqdm(contests)
        stages_ids = []

        resources = {contest.resource for contest in contests}
        if len(resources) == 1 and len(contests) > 3:
            resource_event_log = EventLog.objects.create(name='parse_statistic',
                                                         related=contests[0].resource,
                                                         status=EventStatus.IN_PROGRESS)
        else:
            resource_event_log = None

        problems_values_fields = (
            ('language', '_languages'),
            ('verdict', '_verdicts'),
        )

        processed_group = set()
        for contest in progress_bar:
            if stop_on_error and has_error:
                break
            if resource_event_log:
                message = f'progress {n_contest_progress} of {len(contests)} ({count} parsed), contest = {contest}'
                resource_event_log.update_message(message)
            n_contest_progress += 1

            channel_layer_handler.set_contest(contest)
            resource = contest.resource
            if not hasattr(resource, 'module'):
                self.logger.warning(f'contest = {contest}')
                self.logger.warning(f'resource = {resource}')
                self.logger.error('Not found module')
                continue
            if resource.has_upsolving and not with_stats:
                self.logger.warning(f'Skip parse statistic contest = {contest} because'
                                    f' run without stats and resource has upsolving')
                continue

            group = contest.info.pop('__parse_statistics_group', None)
            if group and group in processed_group:
                self.logger.info(f'Skip contest = {contest} because already processed group = {group}')
                continue
            processed_group.add(group)

            self.logger.info(f'Contest = {contest}')
            progress_bar.set_description(f'contest = {contest}')
            progress_bar.refresh()
            total += 1

            inherit_stage = contest.info.get('_inherit_stage')
            has_stage = hasattr(contest, 'stage')
            if not has_stage and inherit_stage:
                call_command('inherit_stage', contest_id=contest.pk)
                contest.refresh_from_db()
                has_stage = hasattr(contest, 'stage')
                if not has_stage:
                    raise Exception(f'Not found stage for contest = {contest}')
            if has_stage and not ignore_stage:
                self.logger.info(f'update stage = {contest.stage}')
                stages_ids.append(contest.stage.pk)
                count += 1
                continue

            parsed = False
            exception_error = None
            user_info_has_rating = {}
            to_update_socket = contest.is_running() or contest.has_hidden_results or force_socket
            to_calculate_problem_rating = False
            event_log = EventLog.objects.create(name='parse_statistic',
                                                related=contest,
                                                status=EventStatus.IN_PROGRESS)
            contest_log_counter = defaultdict(int)

            try:
                r = {}

                now = timezone_now()
                is_coming = now < contest.start_time
                plugin = resource.plugin.Statistic(contest=contest)

                with transaction.atomic():
                    _ = Contest.objects.select_for_update().get(pk=contest.pk)

                    with REQ:
                        statistics_by_key = {}
                        more_statistics_by_key = {}
                        statistics_ids = set()
                        has_statistics = False
                        if not no_update_results:
                            statistics = Statistics.objects.filter(contest=contest).select_related('account')
                            if users:
                                statistics = statistics.filter(account__key__in=users)
                            for s in statistics.iterator():
                                addition = s.addition or {}
                                if with_stats and not addition.get('_skip_on_update'):
                                    statistics_by_key[s.account.key] = addition
                                    more_statistics_by_key[s.account.key] = {
                                        'pk': s.pk,
                                        'place': s.place,
                                        'score': s.solving,
                                        '_no_update_n_contests': s.skip_in_stats,
                                    }
                                    has_statistics = True
                                statistics_ids.add(s.pk)
                        standings = plugin.get_standings(users=copy.deepcopy(users), statistics=statistics_by_key)
                        has_standings_result = bool(standings.get('result'))

                        if resource.has_upsolving:
                            result = standings.setdefault('result', {})
                            for member, row in statistics_by_key.items():
                                result_row = result.get(member)
                                stat = more_statistics_by_key[member]
                                if result_row is None:
                                    has_problem_result = any('result' in p for p in row.get('problems', {}).values())
                                    if has_problem_result:
                                        continue
                                    if row.get('_no_update_n_contests') and stat['_no_update_n_contests']:
                                        statistics_ids.remove(stat['pk'])
                                        contest_log_counter['skip_no_update'] += 1
                                        continue
                                    row = copy.deepcopy(row)
                                    row['member'] = member
                                    row['_no_update_n_contests'] = True
                                    result[member] = row
                                elif (
                                    result_row.get('_no_update_n_contests') and
                                    canonize(result_row.get('problems')) == canonize(row.get('problems')) and
                                    ('solving' not in result_row or isclose(result_row['solving'], stat['score'])) and
                                    ('place' not in result_row or str(result_row['place']) == str(stat['place']))
                                ):
                                    if row.get('_no_update_n_contests') and stat['_no_update_n_contests']:
                                        statistics_ids.remove(stat['pk'])
                                        contest_log_counter['skip_no_update'] += 1
                                        result.pop(member)

                        keep_results = standings.pop('keep_results', False)
                        if keep_results:
                            result = standings.setdefault('result', {})
                            for member, row in statistics_by_key.items():
                                if member in result:
                                    continue
                                pk = more_statistics_by_key[member]['pk']
                                if pk in statistics_ids:
                                    statistics_ids.remove(pk)
                                    row = copy.deepcopy(row)
                                    row['member'] = member
                                    row['_skip_update'] = True
                                    contest_log_counter['skip_update'] += 1
                                    result[member] = row

                        if get_item(resource, 'info.standings.skip_not_solving'):
                            result = standings.setdefault('result', {})
                            for member in list(result):
                                row = result[member]
                                if not row.get('solving'):
                                    contest_log_counter['skip_not_solving'] += 1
                                    result.pop(member)

                        for key, more_stat in more_statistics_by_key.items():
                            statistics_by_key[key].update(more_stat)

                    for field, attr in (
                        ('url', 'standings_url'),
                        ('contest_url', 'url'),
                        ('title', 'title'),
                        ('invisible', 'invisible'),
                        ('duration_in_secs', 'duration_in_secs'),
                        ('kind', 'kind'),
                        ('standings_kind', 'standings_kind'),
                        ('is_rated', 'is_rated'),
                    ):
                        if field in standings and standings[field] != getattr(contest, attr):
                            setattr(contest, attr, standings[field])
                            contest.save(update_fields=[attr])

                    if 'series' in standings:
                        contest.set_series(standings.pop('series'))

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
                            contest.save(update_fields=['info'])

                    info_fields = standings.pop('info_fields', [])
                    info_fields += ['divisions_order', 'divisions_addition', 'advance', 'grouped_team', 'fields_values',
                                    'default_problem_full_score', 'custom_start_time', 'skip_problem_rating']
                    info_fields_values = {}
                    for field in info_fields:
                        field_value = standings.get(field)
                        if field_value is not None:
                            info_fields_values[field] = field_value
                            if contest.info.get(field) != field_value:
                                contest.info[field] = field_value
                                contest.save(update_fields=['info'])

                    update_writers(contest, standings.pop('writers', None))

                    standings_hidden_fields = list(standings.pop('hidden_fields', []))
                    standings_hidden_fields_mapping = dict()
                    standings_hidden_fields_set = set(standings_hidden_fields)

                    standings_problems = standings.pop('problems', None)
                    result = standings.setdefault('result', {})

                    if is_coming:
                        for r in result.values():
                            for field in ('place', 'solving', 'problems', 'penalty'):
                                if field in r:
                                    r.pop(field)
                        standings_problems = {}

                    if no_update_results:
                        if standings_problems and not no_update_problems:
                            standings_problems = plugin.merge_dict(standings_problems, contest.info.get('problems'))
                            update_problems(contest, standings_problems, force=force_problems)
                        count += 1
                        event_log.update_status(status=EventStatus.CANCELLED, message='no_update_results')
                        continue

                    if resource.has_standings_renamed_account:
                        renaming_qs = AccountRenaming.objects.filter(resource=resource, old_key__in=result.keys())
                        renaming_qs = renaming_qs.values_list('old_key', 'new_key')
                        for old_key, new_key in renaming_qs:
                            if old_key in result:
                                if new_key is None:
                                    result.pop(old_key)
                                else:
                                    result[new_key] = result.pop(old_key)
                                    result[new_key]['member'] = new_key
                                    result[new_key]['_no_update_name'] = True
                                    result[new_key].pop('info', None)

                    parse_info = contest.info.get('parse', {})
                    resource_statistics = resource.info.get('statistics') or {}
                    wait_rating = resource_statistics.get('wait_rating', {})
                    has_hidden = standings.pop('has_hidden', False)
                    with_link_accounts = standings.pop('link_accounts', False)
                    is_major_kind = resource.is_major_kind(contest.kind)
                    custom_fields_types = standings.pop('fields_types', {})
                    standings_kinds = set(Contest.STANDINGS_KINDS.keys())
                    has_more_solving = bool(contest.info.get('_more_solving'))
                    updated_statistics_ids = list()
                    contest_timeline = contest.get_timeline_info()
                    lazy_fetch_accounts = standings.pop('lazy_fetch_accounts', False)
                    has_problem_stats = False

                    results = []
                    if result or users:
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
                        medals_skip_places = defaultdict(int)

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

                            skip_result = bool(r.get('_no_update_n_contests'))
                            last_activity = contest.start_time
                            if r.get('submit_time') and 'timestamp' in custom_fields_types.get('submit_time', []):
                                last_activity = datetime.fromtimestamp(r['submit_time'], tz=timezone.utc)
                            total_problems_solving = 0

                            def update_problems_info():
                                nonlocal last_activity, total_problems_solving, has_problem_stats

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
                                        if not r.get('division'):
                                            continue
                                        p = p.setdefault(r['division'], {})
                                        standings_p = standings_p.get(r['division'], [])
                                    p = p.setdefault(k, {})

                                    result_str = str(v['result'])
                                    is_accepted = result_str.startswith('+')
                                    is_hidden = result_str.startswith('?')
                                    is_score = result_str and result_str[0].isdigit()
                                    result_num = as_number(v['result'], force=True)

                                    if result_str and result_str[0] not in '+-?':
                                        standings_kinds.discard('icpc')
                                    if result_str and result_num is None:
                                        standings_kinds.discard('scoring')

                                    scored = is_accepted
                                    try:
                                        scored = scored or float(v['result']) > 0
                                    except Exception:
                                        pass

                                    if scored:
                                        total_problems_solving += 1 if is_accepted else result_num

                                    default_full_score = (
                                        contest.info.get('default_problem_full_score')
                                        or resource_statistics.get('default_problem_full_score')
                                    )
                                    if default_full_score and is_score:
                                        if default_full_score == 'max':
                                            p['max_score'] = max(p.get('max_score', float('-inf')), result_num)
                                        elif default_full_score == 'min':
                                            p['min_score'] = min(p.get('min_score', float('inf')), result_num)
                                        else:
                                            if 'full_score' not in p:
                                                for i in standings_p:
                                                    if get_problem_key(i) == k and 'full_score' in i:
                                                        p['full_score'] = i['full_score']
                                                        break
                                                else:
                                                    p['full_score'] = default_full_score
                                            if 'partial' not in v and p['full_score'] - result_num > EPS:
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

                                    if skip_result:
                                        continue

                                    if ac and v.get('time'):
                                        if contest.info.get('with_time_from_timeline') and 'time_in_seconds' not in v:
                                            if contest_timeline:
                                                v['time_in_seconds'] = time_in_seconds(contest_timeline, v['time'])

                                        in_seconds = v.get('time_in_seconds')
                                        if in_seconds is not None:
                                            activity_time = contest.start_time + timedelta(seconds=in_seconds)
                                            if contest.start_time <= activity_time <= contest.end_time:
                                                last_activity = max(last_activity, activity_time)
                                        cmp_seconds = in_seconds
                                        if v.get('first_ac') or v.get('first_ac_of_all'):
                                            cmp_seconds = -1
                                        if in_seconds is not None:
                                            first_ac = p.setdefault('first_ac', {})
                                            delta = cmp_seconds - first_ac.get('_cmp_seconds', float('inf'))
                                            if '_cmp_seconds' in first_ac and abs(delta) < EPS:
                                                first_ac['accounts'].append(r['member'])
                                            if '_cmp_seconds' not in first_ac or delta < 0:
                                                first_ac['_cmp_seconds'] = cmp_seconds
                                                first_ac['in_seconds'] = in_seconds
                                                first_ac['time'] = v['time']
                                                first_ac['accounts'] = [r['member']]
                                            if resource_statistics.get('with_last_ac'):
                                                last_ac = p.setdefault('last_ac', {})
                                                if '_cmp_seconds' in last_ac and abs(delta) > EPS:
                                                    last_ac['accounts'].append(r['member'])
                                                if '_cmp_seconds' not in last_ac or delta > 0:
                                                    last_ac['_cmp_seconds'] = cmp_seconds
                                                    last_ac['in_seconds'] = in_seconds
                                                    last_ac['time'] = v['time']
                                                    last_ac['accounts'] = [r['member']]

                                    if r.get('_skip_for_problem_stat') or not is_new:
                                        continue

                                    p['n_teams'] = p.get('n_teams', 0) + 1
                                    if ac:
                                        p['n_accepted'] = p.get('n_accepted', 0) + 1
                                    elif scored and v.get('partial'):
                                        p['n_partial'] = p.get('n_partial', 0) + 1
                                    elif is_hidden:
                                        p['n_hidden'] = p.get('n_hidden', 0) + 1
                                    has_problem_stats = True

                                if 'default_problem_full_score' in contest.info and solved and 'solved' not in r:
                                    r['solved'] = solved

                            default_division = contest.info.get('default_division')
                            if default_division and 'division' not in r:
                                r['division'] = default_division

                            update_problems_info()

                            if has_more_solving and 'solving' in r:
                                more_solving = r['solving'] - total_problems_solving
                                if more_solving:
                                    r['_more_solving'] = more_solving

                            r.setdefault('last_activity', last_activity)
                            results.append(r)

                        if len(standings_kinds) == 1:
                            standings_kind = standings_kinds.pop()
                            if contest.standings_kind != standings_kind:
                                contest.standings_kind = standings_kind
                                contest.save(update_fields=['standings_kind'])

                        if not lazy_fetch_accounts:
                            members = [r['member'] for r in results]
                            accounts = resource.account_set.filter(key__in=members)
                            accounts = {a.key: a for a in accounts}

                        if contest.set_matched_coders_to_members:
                            matched_coders = contest.account_matchings
                            matched_coders = matched_coders.filter(account__coders=F('coder'))
                            matched_coders = matched_coders.values('name', 'statistic_id', 'coder__username',
                                                                   'coder__country')
                            matched_coders = {
                                (m['name'], m['statistic_id']): (m['coder__username'], m['coder__country'])
                                for m in matched_coders
                            }

                        for r in tqdm(results, desc='update results'):
                            skip_update = bool(r.get('_skip_update'))
                            if skip_update:
                                continue
                            member = r.pop('member')
                            skip_result = bool(r.get('_no_update_n_contests'))

                            if lazy_fetch_accounts:
                                account, account_created = Account.objects.get_or_create(resource=resource, key=member)
                            elif member not in accounts:
                                account = resource.account_set.create(key=member)
                                accounts[member] = account
                                account_created = True
                            else:
                                account = accounts[member]
                                account_created = False

                            stat = statistics_by_key.get(member, {})

                            previous_member = r.pop('previous_member', None)
                            if previous_member and previous_member in statistics_by_key:
                                stat = statistics_by_key[previous_member]
                                previous_account = resource.account_set.filter(key=previous_member).first()
                                if previous_account:
                                    account = rename_account(previous_account, account)

                            result_submissions = r.pop('submissions', [])
                            if contest.has_submissions and not result_submissions:
                                self.logger.warning(f'Not found submissions for account = {account}')

                            def update_addition_fields():
                                addition_fields = parse_info.get('addition_fields', [])
                                if not stat or not addition_fields:
                                    return
                                for d in addition_fields:
                                    k = d['out']
                                    value = r.get(d['field'])
                                    pvalue = stat.get(d.get('vs_field', k))

                                    on_update_value = d.get('on_update_value')
                                    if on_update_value == 'now':
                                        fields_types[k].add('timestamp')
                                    elif on_update_value:
                                        raise ValueError(f'Unkonwn value = {on_update_value} in addition field = {d}')

                                    if d.get('skip_after_end') and contest.end_time < now:
                                        value = stat.get(k)
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
                                        value = stat.get(k)
                                    if value is not None:
                                        r[k] = value

                            def update_account_time():
                                if (
                                    contest.info.get('_no_update_account_time') or
                                    skip_result or
                                    contest.end_time > now or
                                    users
                                ):
                                    return

                                nonlocal n_account_time_update
                                no_rating = with_stats and (
                                    ('new_rating' in stat) + ('rating_change' in stat) + ('old_rating' in stat) < 2
                                )

                                updated_delta = resource_statistics.get('account_updated_delta', {'days': 1})
                                updated = now + timedelta(**updated_delta)

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

                                to_update_account = (
                                    account_created
                                    or not has_statistics
                                    or update_on_parsed_time
                                    or (update_without_new_rating and no_rating)
                                )

                                title_re = wait_rating.get('title_re')
                                wait_days = wait_rating.get('days')
                                if (
                                    not to_update_account
                                    and no_rating
                                    and wait_rating
                                    and contest.end_time + timedelta(days=wait_days) > now
                                    and (not title_re or re.search(title_re, contest.title))
                                ):
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
                                            self.logger.debug(colored_format_exc())
                                            user_info_has_rating[division] = False
                                    if user_info_has_rating[division]:
                                        to_update_account = True

                                if to_update_account:
                                    n_account_time_update += 1
                                    contest_log_counter['account_time_update'] += 1
                                    account.updated = updated
                                    account.save(update_fields=['updated'])

                            def update_account_info():
                                if contest.info.get('_push_name_instead_key'):
                                    r['_name_instead_key'] = True
                                if contest.info.get('_push_name_instead_key_to_account'):
                                    account.info['_name_instead_key'] = True
                                    account.save()

                                no_update_name = r.pop('_no_update_name', False)
                                no_update_name |= 'team_id' in r and '_field_update_name' not in r
                                field_update_name = r.pop('_field_update_name', 'name')
                                if r.get(field_update_name):
                                    r[field_update_name] = canonize_name(r[field_update_name])
                                    if (
                                        not no_update_name and
                                        account.name != r[field_update_name] and
                                        account.key != r[field_update_name]
                                    ):
                                        account.name = r[field_update_name]
                                        account.save(update_fields=['name'])

                                country = r.get('country', None)
                                if country:
                                    country = countrier.get(country)
                                    if country and country != account.country:
                                        account.country = country
                                        account.save(update_fields=['country'])

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
                                if medals and contest.end_time < now and not contest.has_hidden_results:
                                    medals_divisions = contest.info.get('standings', {}).get('medals_divisions')
                                    k = 'medal'
                                    r.pop(k, None)
                                    if 'place' in r and (not medals_divisions or r.get('division') in medals_divisions):
                                        place = get_number_from_str(r['place'])
                                        if (
                                            member in contest.info.get('standings', {}).get('medals_skip', [])
                                            or r.get('_skip_medal')
                                        ):
                                            medals_skip.add(member)
                                            medals_skip_places[place] += 1
                                        elif place:
                                            place -= len(medals_skip) - medals_skip_places.get(place, 0)
                                            for medal in medals:
                                                if (
                                                    'count' in medal and place <= medal['count']
                                                    or 'score' in medal and r.get('solving', 0) >= medal['score']
                                                ):
                                                    r[k] = medal['name']
                                                    if 'field' in medal:
                                                        field = medal['field']
                                                        if (
                                                            not Statistics.is_special_addition_field(field)
                                                            and field not in hidden_fields
                                                        ):
                                                            standings_hidden_fields.append(field)
                                                            hidden_fields.add(field)
                                                        r[field] = medal['value']
                                                        r[f'_{k}_title_field'] = field
                                                    break
                                                if 'count' in medal:
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
                                        if not r.get('division'):
                                            continue
                                        p = p.setdefault(r['division'], {})
                                    p = p.setdefault(k, {})
                                    if 'first_ac' not in p:
                                        continue

                                    if member in p['first_ac']['accounts']:
                                        v['first_ac'] = True

                            def get_addition():
                                place = r.pop('place', None)
                                defaults = {
                                    'place': place,
                                    'place_as_int': place if place == UNCHANGED else get_number_from_str(place),
                                    'solving': r.pop('solving', 0),
                                    'upsolving': r.pop('upsolving', 0),
                                    'skip_in_stats': skip_result,
                                    'advanced': bool(r.get('advanced')),
                                    'last_activity': r.pop('last_activity', None),
                                }
                                defaults = {k: v for k, v in defaults.items() if v != UNCHANGED}

                                addition = type(r)()
                                nonlocal addition_was_ordereddict
                                addition_was_ordereddict |= isinstance(addition, OrderedDict)
                                previous_fields = set()
                                for k, v in r.items():
                                    orig_k = k
                                    is_hidden_field = orig_k in standings_hidden_fields_set
                                    k = normalize_field(k)
                                    if is_hidden_field:
                                        standings_hidden_fields_mapping[orig_k] = k
                                        hidden_fields.add(k)
                                    if k not in fields_set:
                                        fields_set.add(k)
                                        fields.append(k)
                                    if not skip_result:
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
                                    if not skip_result:
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
                                    contest.full_duration < resource.module.long_contest_idle and
                                    'penalty' in fields_set
                                )

                                if not try_calculate_time:
                                    defaults['addition'] = addition

                                return defaults, addition, try_calculate_time

                            def update_after_update_or_create(statistic, created, addition, try_calculate_time):
                                problems = r.get('problems', {})

                                if not created:
                                    nonlocal calculate_time
                                    statistics_ids.discard(statistic.pk)

                                    if contest_timeline and try_calculate_time:
                                        p_problems = statistic.addition.get('problems', {})

                                        ts = int((now - contest.start_time).total_seconds())
                                        ts = min(ts, contest.duration_in_secs)
                                        time = time_in_seconds_format(contest_timeline, ts, num=2)

                                        for k, v in problems.items():
                                            v_result = v.get('result', '')
                                            if isinstance(v_result, str) and '?' in v_result:
                                                calculate_time = True
                                            if 'time' in v or 'result' not in v:
                                                continue
                                            p = p_problems.get(k, {})
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

                                previous_problems = stat.get('problems', {})
                                for k, problem in problems.items():
                                    previous_problem = previous_problems.get(k, {})
                                    if (
                                        problem.get('result') != previous_problem.get('result') or
                                        problem.get('time') != previous_problem.get('time') or
                                        force_socket
                                    ):
                                        updated_statistics_ids.append(statistic.pk)
                                        break

                                if str(statistic.place) != str(stat.get('place')):
                                    updated_statistics_ids.append(statistic.pk)

                                if try_calculate_time:
                                    statistic.addition = addition
                                    statistic.save()

                            @suppress_db_logging_context()
                            def update_submissions(statistic, result_submissions):
                                if not result_submissions:
                                    return

                                if not contest.has_submissions:
                                    contest.has_submissions = True
                                    contest.save(update_fields=['has_submissions'])

                                statistic_problems = statistic.addition.get('problems', {})
                                updated_problems = False
                                submission_ids = set()
                                for result_submission in result_submissions:
                                    language = Language.cached_get(result_submission['language'])
                                    verdict = Verdict.cached_get(result_submission['verdict'])
                                    problem = Problem.cached_get(contest=contest,
                                                                 short=result_submission['problem_short'])
                                    problem_short = result_submission['problem_short']

                                    defaults = {
                                        'problem': problem,
                                        'contest_time': result_submission['contest_time'],
                                        'language': language,
                                        'verdict': verdict,
                                        'time': result_submission.get('time'),
                                        'current_result': result_submission.get('current_result'),
                                        'current_attempt': result_submission.get('current_attempt'),
                                        'problem_key': problem.key if problem is not None else None,
                                    }

                                    for field in ('run_time', 'failed_test'):
                                        if field in result_submission:
                                            defaults[field] = result_submission[field]

                                    run_time = result_submission.get('run_time')
                                    if run_time is not None:
                                        defaults['run_time'] = run_time

                                    submission, submission_created = Submission.objects.update_or_create(
                                        account=account,
                                        contest=contest,
                                        statistic=statistic,
                                        secondary_key=result_submission['id'],
                                        problem_short=problem_short,
                                        defaults=defaults,
                                    )
                                    submission_ids.add(submission.pk)

                                    contest_log_counter['submissions_total'] += 1
                                    if submission_created:
                                        contest_log_counter['submissions_created'] += 1

                                    if result_submission.get('testing') and not contest.has_submissions_tests:
                                        contest.has_submissions_tests = True
                                        contest.save(update_fields=['has_submissions_tests'])

                                    if 'testing' in result_submission and submission_created:
                                        update_fields = {}
                                        for testing in result_submission['testing']:
                                            verdict = Verdict.cached_get(testing['verdict'])
                                            test_number = testing.get('test_number')
                                            run_time = testing.get('run_time')

                                            if (
                                                not verdict.solved and
                                                test_number is not None and
                                                'failed_test' not in defaults and
                                                ('failed_test' not in update_fields
                                                 or test_number < update_fields['failed_test'])
                                            ):
                                                update_fields['failed_test'] = test_number

                                            if (
                                                verdict.solved and
                                                run_time is not None and
                                                'run_time' not in defaults and
                                                ('run_time' not in update_fields
                                                 or run_time > update_fields['run_time'])
                                            ):
                                                update_fields['run_time'] = run_time

                                            _, testing_created = Testing.objects.update_or_create(
                                                submission=submission,
                                                secondary_key=testing['id'],
                                                defaults={
                                                    'verdict': verdict,
                                                    'test_number': test_number,
                                                    'run_time': run_time,
                                                    'contest_time': testing.get('contest_time'),
                                                    'time': testing.get('time'),
                                                }
                                            )
                                            contest_log_counter['testing_total'] += 1
                                            if testing_created:
                                                contest_log_counter['testing_created'] += 1

                                        if update_fields:
                                            for field, value in update_fields.items():
                                                setattr(submission, field, value)
                                            submission.save(update_fields=list(update_fields))

                                    statistic_problem = statistic_problems.get(problem_short, {})
                                    if (
                                        statistic_problem and
                                        submission.current_result == statistic_problem.get('result')
                                    ):
                                        fields_values = (
                                            ('language', submission.language_id),
                                            ('verdict', submission.verdict_id),
                                            ('run_time', submission.run_time),
                                            ('failed_test', submission.failed_test),
                                        )
                                        if contest.calculate_time and not is_solved(submission.current_result):
                                            time = time_in_seconds_format(contest_timeline,
                                                                          int(submission.contest_time.total_seconds()),
                                                                          num=2)
                                            fields_values += (('time', time),)

                                        for field, value in fields_values:
                                            if value is not None and statistic_problem.get(field) != value:
                                                statistic_problem[field] = value
                                                updated_problems = True
                                if update_problems_values(statistic.addition):
                                    updated_problems = True
                                if updated_problems:
                                    statistic.save(update_fields=['addition'])
                                if os.environ.get('DELETE_SUBMISSIONS'):
                                    extra = Submission.objects.filter(statistic=statistic)
                                    extra = extra.exclude(pk__in=submission_ids)
                                    delete_info = extra.delete()
                                    n_deleted, delete_info = delete_info
                                    if n_deleted:
                                        self.logger.warning(f'Delete extra submissions: {delete_info}')
                                        contest_log_counter['submissions_deleted'] += n_deleted

                            def update_problems_values(addition):
                                problems = addition.get('problems', {})
                                updated_addition = False
                                for field, out in problems_values_fields:
                                    values = set()
                                    for problem in problems.values():
                                        value = problem.get(field)
                                        if value:
                                            problems_values[out].add(value)
                                            values.add(value)
                                    if out not in addition and values:
                                        addition[out] = list(values)
                                        updated_addition = True
                                return updated_addition

                            def link_account(statistic):
                                account_keys = set()
                                for member in statistic.addition.get('_members', []):
                                    if not member:
                                        continue
                                    account_key = member.get('account')
                                    if not account_key:
                                        continue
                                    account_keys.add(account_key)
                                link_accounts = resource.account_set.filter(key__in=account_keys)
                                link_accounts = link_accounts.prefetch_related('coders')
                                for link_account in link_accounts:
                                    coders = link_account.coders.all()
                                    if len(coders) != 1:
                                        continue
                                    coder = coders[0]
                                    if coder.account_set.filter(pk=statistic.account.pk).exists():
                                        continue
                                    statistic.account.coders.add(coder)
                                    NotificationMessage.link_accounts(to=coder, accounts=[statistic.account])

                            def set_matched_coders_to_members(statistic):
                                to_update = False
                                for member in statistic.addition.get('_members', []):
                                    if 'name' not in member or len(member) > 1:
                                        continue
                                    matched_coder_key = (member['name'], statistic.pk)
                                    if matched_coder_key in matched_coders:
                                        member['coder'], country = matched_coders[matched_coder_key]
                                        if country:
                                            statistic.addition.setdefault('_countries', []).append(country)
                                        to_update = True
                                if to_update:
                                    statistic.save(update_fields=['addition'])

                            update_addition_fields()
                            update_account_time()
                            update_account_info()
                            update_stat_info()
                            update_problems_values(r)
                            if not users:
                                update_problems_first_ac()
                            defaults, addition, try_calculate_time = get_addition()

                            statistic, statistic_created = Statistics.objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )
                            n_statistics_total += 1
                            n_statistics_created += statistic_created
                            contest_log_counter['statistics_total'] += 1
                            if statistic_created:
                                contest_log_counter['statistics_created'] += 1

                            update_after_update_or_create(statistic, statistic_created, addition, try_calculate_time)

                            update_submissions(statistic, result_submissions)

                            if with_link_accounts:
                                link_account(statistic)

                            if contest.set_matched_coders_to_members:
                                set_matched_coders_to_members(statistic)

                            has_subscription_update = (
                                account.is_subscribed
                                and not skip_result
                                and not addition.get('_skip_subscription')
                                and (
                                    statistic_created
                                    or stat.get('score', 0) < statistic.solving + EPS
                                )
                            )
                            if has_subscription_update:
                                subscriptions_filter = Q(resource__isnull=True) | Q(resource=resource)
                                subscriptions_filter &= Q(contest__isnull=True) | Q(contest=contest)
                                subscriptions_filter &= (
                                    Q(account=account)
                                    | Q(coder_chat__coders__account=account)
                                    | Q(coder_list__values__account=account)
                                    | Q(coder_list__values__coder__account=account)
                                )
                                subscriptions = Subscription.objects.filter(subscriptions_filter)
                                for subscription in subscriptions:
                                    pass

                        if not users:
                            if has_hidden != contest.has_hidden_results:
                                contest.has_hidden_results = has_hidden
                                contest.save(update_fields=['has_hidden_results'])

                            for field, values in problems_values.items():
                                if values:
                                    field = field.strip('_')
                                    values = list(sorted(values))
                                    if canonize(values) != canonize(contest.info.get(field)):
                                        contest.info[field] = values
                            for _, field in problems_values_fields:
                                contest_field = field.strip('_')
                                if field in fields_set or not contest.info.get(contest_field):
                                    continue
                                fields_set.add(field)
                                fields.append(field)

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
                                n_deleted, _ = delete_info
                                contest_log_counter['statistics_deleted'] += n_deleted

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
                            for k, v in custom_fields_types.items():
                                fields_types.setdefault(k, []).extend(v)
                            for k, v in fields_types.items():
                                if set(v) == {'float', 'int'}:
                                    v[:] = ['float']
                            contest.info['fields_types'] = fields_types

                            if calculate_time and not contest.calculate_time:
                                contest.calculate_time = True

                            contest.n_statistics = n_statistics.pop('__total__', 0)
                            if contest.end_time <= now and (contest.parsed_time is None or contest.parsed_time < now):
                                resource.contest_update_time = now
                                resource.save(update_fields=['contest_update_time'])
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
                                            if has_problem_stats:
                                                p.setdefault('n_total', n_statistics[d])
                                            p.get('first_ac', {}).pop('_cmp_seconds', None)
                                            p.get('last_ac', {}).pop('_cmp_seconds', None)
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
                                        if has_problem_stats:
                                            p.setdefault('n_total', contest.n_statistics)
                                        p.get('first_ac', {}).pop('_cmp_seconds', None)
                                        p.get('last_ac', {}).pop('_cmp_seconds', None)
                                        if key in problems_ratings:
                                            p['rating'] = problems_ratings[key]

                                if not no_update_problems:
                                    update_problems(contest, problems=standings_problems, force=force_problems)
                            contest.save()

                            if to_update_socket:
                                update_standings_socket(contest, updated_statistics_ids)

                            to_calculate_problem_rating = (
                                resource.has_problem_rating and
                                contest.end_time < now and
                                not contest.has_hidden_results and
                                not standings.get('timing_statistic_delta')
                            )

                            progress_bar.set_postfix(n_fields=len(fields), n_updated=len(updated_statistics_ids))
                    else:
                        if standings_problems is not None and standings_problems and not no_update_problems:
                            standings_problems = plugin.merge_dict(standings_problems, contest.info.get('problems'))
                            update_problems(contest, problems=standings_problems, force=force_problems or not users)

                    if not users:
                        timing_delta = None
                        if contest.full_duration < resource.module.long_contest_idle:
                            timing_delta = standings.get('timing_statistic_delta', timing_delta)
                            if now < contest.end_time:
                                timing_delta = parse_info.get('timing_statistic_delta', timing_delta)
                        if updated_statistics_ids and contest.end_time < now < contest.end_time + timedelta(hours=1):
                            timing_delta = timing_delta or timedelta(minutes=20)
                        if has_hidden and contest.end_time < now < contest.end_time + timedelta(days=1):
                            timing_delta = timing_delta or timedelta(minutes=60)
                        if wait_rating and not has_statistics and results and 'days' in wait_rating:
                            timing_delta = timing_delta or timedelta(days=wait_rating['days']) / 10
                        timing_delta = timedelta(**timing_delta) if isinstance(timing_delta, dict) else timing_delta
                        if timing_delta is not None:
                            self.logger.info(f'Statistic timing delta = {timing_delta}')
                            contest.info['_timing_statistic_delta_seconds'] = timing_delta.total_seconds()
                        else:
                            contest.info.pop('_timing_statistic_delta_seconds', None)
                        if not info_fields_values.get('_reparse_statistics'):
                            contest.info.pop('_reparse_statistics', None)
                        contest.save()
                    else:
                        without_calculate_rating_prediction = True
                        to_calculate_problem_rating = False

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
                                continue
                        elif action == 'url':
                            contest.url = args[0]
                            contest.save()

                reparse_statistics = contest.info.get('_reparse_statistics')
                if not reparse_statistics:
                    if resource.rating_prediction and not without_calculate_rating_prediction and contest.pk:
                        call_command('calculate_rating_prediction', contest=contest.pk)
                        contest.refresh_from_db()
                        n_calculated_rating_prediction += 1

                    if to_calculate_problem_rating and not without_calculate_problem_rating and contest.pk:
                        call_command('calculate_problem_rating', contest=contest.pk, force=force_problems)
                        contest.refresh_from_db()
                        n_calculated_problem_rating += 1

                    if not without_fill_coder_problems and contest.pk:
                        if users:
                            users_qs = Account.objects.filter(resource=resource, key__in=users)
                            users_coders = Coder.objects.filter(Exists(users_qs.filter(pk=OuterRef('account'))))
                            users_coders = users_coders.values_list('username', flat=True)
                            if users_coders:
                                call_command('fill_coder_problems', contest=contest.pk, coders=users_coders)
                        else:
                            call_command('fill_coder_problems', contest=contest.pk)

                if has_standings_result:
                    count += 1
                parsed = True
            except (ExceptionParseStandings, InitModuleException, ProxyLimitReached) as e:
                exception_error = str(e)
                progress_bar.set_postfix(exception=str(e), cid=str(contest.pk))
            except Exception as e:
                exception_error = str(e)
                self.logger.debug(colored_format_exc())
                self.logger.warning(f'contest = {contest}, row = {r}')
                self.logger.error(f'parse_statistic exception: {e}')
                has_error = True
                if stop_on_error:
                    print(colored_format_exc())

            if not users:
                module = resource.module
                delay = module.max_delay_after_end
                reparse_statistics = contest.info.get('_reparse_statistics')
                if reparse_statistics or contest.end_time < now or not module.long_contest_divider:
                    delay = min(delay, module.delay_on_success if parsed else module.delay_on_error)
                if now < contest.end_time and module.long_contest_divider:
                    delay = min(delay, contest.full_duration / module.long_contest_divider)
                if not parsed and contest.end_time < now < contest.end_time + module.shortly_after:
                    delay = min(delay, module.delay_shortly_after)
                if now < contest.end_time < now + delay:
                    delay = min(delay, contest.end_time + (module.min_delay_after_end or timedelta(minutes=7)) - now)
                if '_timing_statistic_delta_seconds' in contest.info:
                    timing_delta = timedelta(seconds=contest.info['_timing_statistic_delta_seconds'])
                    delay = min(delay, timing_delta)
                contest.statistic_timing = now + delay
                contest.save(update_fields=['statistic_timing'])
                self.logger.info(f'statistics delay = {delay} ({contest.statistic_timing})')

                if parsed and not no_update_results:
                    stages = Stage.objects.filter(
                        ~Q(pk__in=stages_ids),
                        contest__start_time__lte=contest.start_time,
                        contest__end_time__gte=contest.end_time,
                        contest__resource=resource,
                    )
                    for stage in stages:
                        if Contest.objects.filter(pk=contest.pk, **stage.filter_params).exists():
                            contest_log_counter['stage'] += 1
                            stages_ids.append(stage.pk)

            status = EventStatus.COMPLETED if parsed else EventStatus.FAILED
            messages = []
            if exception_error:
                messages += [f'exception error = {exception_error}']
            if contest_log_counter:
                messages += [f'log_counter = {dict(contest_log_counter)}']
            event_log.update_status(status=status, message='\n\n'.join(messages))
            if users:
                event_log.delete()
            self.logger.info(f'log_counter = {dict(contest_log_counter)}')
            channel_layer_handler.send_done(done=parsed)

        @lru_cache(maxsize=None)
        def update_stage(stage):
            exclude_stages = stage.score_params.get('advances', {}).get('exclude_stages', [])
            ret = stage.pk in stages_ids
            if exclude_stages:
                for s in Stage.objects.filter(pk__in=exclude_stages):
                    if update_stage(s):
                        ret = True
            if ret:
                try:
                    event_log = EventLog.objects.create(name='parse_statistic',
                                                        related=stage,
                                                        status=EventStatus.IN_PROGRESS)
                    channel_layer_handler.set_contest(stage.contest)
                    stage.update()
                    channel_layer_handler.send_done(done=True)
                    event_log.update_status(EventStatus.COMPLETED)
                except Exception as e:
                    channel_layer_handler.send_done(done=False)
                    event_log.update_status(EventStatus.FAILED, message=str(e))
                    raise e
            return ret

        if stages_ids:
            for stage in tqdm(Stage.objects.filter(pk__in=stages_ids), total=len(stages_ids), desc='getting stages'):
                if without_stage:
                    self.logger.info(f'Skip stage: {stage}')
                else:
                    update_stage(stage)

        if resource_event_log:
            resource_event_log.delete()
        progress_bar.close()

        self.logger.info(f'Number of parsed contests: {count} of {total}')
        if n_calculated_problem_rating:
            self.logger.info(f'Number of calculate rating problem: {n_calculated_problem_rating} of {total}')
        if n_calculated_rating_prediction:
            self.logger.info(f'Number of calculate rating prediction: {n_calculated_rating_prediction} of {total}')
        self.logger.info(f'Number of updated account time: {n_account_time_update}')
        self.logger.info(f'Number of created statistics: {n_statistics_created} of {n_statistics_total}')

        root_logger.removeHandler(channel_layer_handler)
        return count, total

    @print_sql_decorator(count_only=True)
    @analyze_db_queries()
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            resources = [Resource.objects.get(host__iregex=r) for r in args.resources]
            contests = Contest.objects.filter(resource__module__resource__in=resources)
        else:
            has_module = Module.objects.filter(resource_id=OuterRef('resource__pk'))
            contests = Contest.objects.annotate(has_module=Exists(has_module)).filter(has_module=True)
        contests = contests.order_by('start_time')

        if args.only_new:
            has_statistics = Statistics.objects.filter(contest_id=OuterRef('pk'))
            contests = contests.annotate(has_statistics=Exists(has_statistics)).filter(has_statistics=False)

        if args.year:
            contests = contests.filter(start_time__year=args.year)

        if args.after:
            contests = contests.filter(start_time__gte=args.after)

        if args.stage:
            contests = contests.filter(stage__isnull=False)

        if args.division:
            contests = contests.filter(info__problems__division__isnull=False)

        if args.with_problems:
            contests = contests.exclude(problem_set=None)

        if args.updated_before:
            contests = contests.filter(updated__lt=arrow.get(args.updated_before).datetime)

        if args.with_medals:
            contests = contests.filter(with_medals=True)

        if args.reparse:
            contests = contests.filter(info___reparse_statistics=True)

        self.parse_statistic(
            contests=contests,
            previous_days=args.days,
            limit=args.limit,
            limit_order=args.limit_order,
            with_check=not args.no_check_timing and not args.reparse,
            stop_on_error=args.stop_on_error,
            random_order=args.random_order,
            no_update_results=args.no_update_results,
            freshness_days=args.freshness_days,
            before_date=args.before_date,
            after_date=args.after_date,
            title_regex=args.event,
            users=args.users,
            with_stats=not args.no_stats,
            update_without_new_rating=args.update_without_new_rating,
            force_problems=args.force_problems,
            force_socket=args.force_socket,
            without_n_statistics=args.without_n_statistics,
            contest_id=args.contest_id,
            query=args.query,
            without_fill_coder_problems=args.without_fill_coder_problems,
            without_calculate_problem_rating=args.without_calculate_problem_rating,
            without_calculate_rating_prediction=args.without_calculate_rating_prediction,
            without_stage=args.without_stage,
            no_update_problems=args.no_update_problems,
            is_rated=args.is_rated,
            for_account=args.for_account,
            ignore_stage=args.ignore_stage,
        )
