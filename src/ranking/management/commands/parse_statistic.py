#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import logging
import operator
import re
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from html import unescape
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
from django.utils import timezone
from django_print_sql import print_sql_decorator

from clist.models import Contest, Resource
from clist.templatetags.extras import (as_number, canonize, get_number_from_str, get_problem_key, get_problem_short,
                                       time_in_seconds, time_in_seconds_format)
from clist.views import update_problems, update_writers
from logify.models import EventLog, EventStatus
from notification.models import NotificationMessage, Subscription
from pyclist.decorators import analyze_db_queries
from ranking.management.commands.parse_accounts_infos import rename_account
from ranking.management.modules.common import REQ
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.models import Account, AccountRenaming, Module, Stage, Statistics
from ranking.utils import account_update_contest_additions
from ranking.views import update_standings_socket
from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.countrier import Countrier
from utils.datetime import parse_datetime
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
        elif self.states[desc] == state:
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

        now = timezone.now()

        contests = contests.select_related('resource__module')

        if query:
            query = eval(query, {'Q': Q, 'F': F}, {})
            contests = contests.filter(query)

        if contest_id:
            contests = contests.filter(pk=contest_id)
        else:
            if with_check:
                if previous_days is not None:
                    contests = contests.filter(end_time__gt=now - timedelta(days=previous_days), end_time__lt=now)
                else:
                    contests = contests.filter(Q(statistic_timing=None) | Q(statistic_timing__lt=now))
                    started = contests.filter(start_time__lt=now, end_time__gt=now, statistics__isnull=False)

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
                    ended = contests.filter(query)

                    contests = Contest.objects.filter(Q(pk__in=started) | Q(pk__in=ended))
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
            contests = contests.order_by('-end_time', '-id')[:limit]

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
        n_upd_account_time = 0
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

            try:
                r = {}

                now = timezone.now()
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
                            for s in statistics:
                                if with_stats:
                                    statistics_by_key[s.account.key] = s.addition or {}
                                    more_statistics_by_key[s.account.key] = {
                                        'place': s.place,
                                        'score': s.solving,
                                    }
                                    has_statistics = True
                                statistics_ids.add(s.pk)
                        standings = plugin.get_standings(users=copy.deepcopy(users), statistics=statistics_by_key)
                        has_standings_result = bool(standings.get('result'))

                        if resource.has_upsolving:
                            result = standings.setdefault('result', {})
                            for member, row in statistics_by_key.items():
                                if member not in result:
                                    has_problem_result = any('result' in p for p in row.get('problems', {}).values())
                                    if has_problem_result:
                                        continue
                                    row = copy.deepcopy(row)
                                    row['member'] = member
                                    row['_no_update_n_contests'] = True
                                    result[member] = row

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
                            contest.save()

                    info_fields = standings.pop('info_fields', [])
                    info_fields += ['divisions_order', 'divisions_addition', 'advance', 'grouped_team', 'fields_values',
                                    'default_problem_full_score', 'custom_start_time']
                    for field in info_fields:
                        if standings.get(field) is not None and contest.info.get(field) != standings[field]:
                            contest.info[field] = standings[field]
                            contest.save()

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

                    parse_info = contest.info.get('parse', {})
                    resource_statistics = resource.info.get('statistics') or {}
                    wait_rating = resource_statistics.get('wait_rating', {})
                    has_hidden = standings.pop('has_hidden', False)
                    link_accounts = standings.pop('link_accounts', False)
                    is_major_kind = resource.is_major_kind(contest.kind)
                    custom_fields_types = standings.pop('fields_types', {})
                    standings_kinds = set(Contest.STANDINGS_KINDS.keys())
                    has_more_solving = bool(contest.info.get('_more_solving'))
                    updated_statistics_ids = list()

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
                                nonlocal last_activity, total_problems_solving

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
                                            timeline = contest.get_timeline_info()
                                            if timeline:
                                                v['time_in_seconds'] = time_in_seconds(timeline, v['time'])

                                        in_seconds = v.get('time_in_seconds')
                                        if in_seconds is not None:
                                            activity_time = contest.start_time + timedelta(seconds=in_seconds)
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

                        members = [r['member'] for r in results]
                        accounts = resource.account_set.filter(key__in=members)
                        accounts = {a.key: a for a in accounts}

                        for r in tqdm(results, desc='update results'):
                            member = r.pop('member')
                            skip_result = bool(r.get('_no_update_n_contests'))

                            account_created = member not in accounts
                            if account_created:
                                account = resource.account_set.create(key=member)
                                accounts[member] = account
                            else:
                                account = accounts[member]

                            stat = statistics_by_key.get(member, {})

                            previous_member = r.pop('previous_member', None)
                            if previous_member and previous_member in statistics_by_key:
                                stat = statistics_by_key[previous_member]
                                previous_account = resource.account_set.filter(key=previous_member).first()
                                if previous_account:
                                    account = rename_account(previous_account, account)

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

                                nonlocal n_upd_account_time
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
                                    n_upd_account_time += 1
                                    account.updated = updated
                                    account.save(update_fields=['updated'])

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
                                    'place_as_int': get_number_from_str(place),
                                    'solving': r.pop('solving', 0),
                                    'upsolving': r.pop('upsolving', 0),
                                    'skip_in_stats': skip_result,
                                    'advanced': bool(r.get('advanced')),
                                    'last_activity': r.pop('last_activity', None),
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
                                        k = re.sub('_+', '_', k)

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
                                    if statistics_ids:
                                        statistics_ids.remove(statistic.pk)

                                    timeline = contest.get_timeline_info()
                                    if timeline and try_calculate_time:
                                        p_problems = statistic.addition.get('problems', {})

                                        ts = int((now - contest.start_time).total_seconds())
                                        ts = min(ts, contest.duration_in_secs)
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

                            def link_account(statistic):
                                account_keys = set()
                                for member in statistic.addition.get('_members', []):
                                    if not member:
                                        continue
                                    account_key = member.get('account')
                                    if not account_key:
                                        continue
                                    account_keys.add(account_key)
                                accounts = resource.account_set.filter(key__in=account_keys).prefetch_related('coders')
                                for account in accounts:
                                    coders = account.coders.all()
                                    if len(coders) != 1:
                                        continue
                                    coder = coders[0]
                                    if coder.account_set.filter(pk=statistic.account.pk).exists():
                                        continue
                                    statistic.account.coders.add(coder)
                                    NotificationMessage.link_accounts(to=coder, accounts=[statistic.account])

                            update_addition_fields()
                            update_account_time()
                            update_account_info()
                            update_stat_info()
                            if not users:
                                update_problems_first_ac()
                            defaults, addition, try_calculate_time = get_addition()

                            statistic, statistics_created = Statistics.objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )
                            n_statistics_total += 1
                            n_statistics_created += statistics_created

                            update_after_update_or_create(statistic, statistics_created, addition, try_calculate_time)

                            if link_accounts:
                                link_account(statistic)

                            has_subscription_update = (
                                account.is_subscribed
                                and not skip_result
                                and not addition.get('_skip_subscription')
                                and (
                                    statistics_created
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
                            for k, v in custom_fields_types.items():
                                fields_types.setdefault(k, []).extend(v)
                            for k, v in fields_types.items():
                                if set(v) == {'float', 'int'}:
                                    v[:] = ['float']
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
                            timing_delta = timing_delta or timedelta(minutes=10)
                        if has_hidden and contest.end_time < now < contest.end_time + timedelta(days=1):
                            timing_delta = timing_delta or timedelta(minutes=30)
                        if wait_rating and not has_statistics and results and 'days' in wait_rating:
                            timing_delta = timing_delta or timedelta(days=wait_rating['days']) / 10
                        timing_delta = timedelta(**timing_delta) if isinstance(timing_delta, dict) else timing_delta
                        if timing_delta is not None:
                            self.logger.info(f'Statistic timing delta = {timing_delta}')
                            contest.info['_timing_statistic_delta_seconds'] = timing_delta.total_seconds()
                        else:
                            contest.info.pop('_timing_statistic_delta_seconds', None)
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
            except (ExceptionParseStandings, InitModuleException) as e:
                exception_error = str(e)
                progress_bar.set_postfix(exception=str(e), cid=str(contest.pk))
            except Exception as e:
                exception_error = str(e)
                self.logger.debug(colored_format_exc())
                self.logger.warning(f'contest = {contest}, row = {r}')
                self.logger.error(f'parse_statistic exception: {e}')
                has_error = True

            event_log.update_status(status=EventStatus.COMPLETED if parsed else EventStatus.FAILED,
                                    message=exception_error)
            if users:
                event_log.delete()

            if not users:
                module = resource.module
                delay = module.delay_on_success if parsed else module.delay_on_error
                if now < contest.end_time and module.long_contest_divider:
                    delay = min(delay, contest.full_duration / module.long_contest_divider)
                if now < contest.end_time < now + delay:
                    delay = min(delay, contest.end_time - now + (module.min_delay_after_end or timedelta(minutes=5)))
                if '_timing_statistic_delta_seconds' in contest.info:
                    timing_delta = timedelta(seconds=contest.info['_timing_statistic_delta_seconds'])
                    delay = min(delay, timing_delta)
                contest.statistic_timing = now + delay
                contest.save(update_fields=['statistic_timing'])

                if parsed and not no_update_results:
                    stages = Stage.objects.filter(
                        ~Q(pk__in=stages_ids),
                        contest__start_time__lte=contest.start_time,
                        contest__end_time__gte=contest.end_time,
                        contest__resource=resource,
                    )
                    for stage in stages:
                        if Contest.objects.filter(pk=contest.pk, **stage.filter_params).exists():
                            stages_ids.append(stage.pk)
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
        self.logger.info(f'Number of updated account time: {n_upd_account_time}')
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
