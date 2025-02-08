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
import django_rq
import humanize
import tqdm as _tqdm
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, F, Max, OuterRef, Prefetch, Q
from django.utils.timezone import now as timezone_now
from django_print_sql import print_sql_decorator

from submissions.models import Language, Submission, Testing, Verdict

from clist.models import Contest, Problem, Resource
from clist.templatetags.extras import (as_number, canonize, get_item, get_number_from_str, get_problem_key,
                                       get_problem_short, get_result_score, get_statistic_stats, is_hidden,
                                       is_scoring_result, is_solved, normalize_field, time_in_seconds,
                                       time_in_seconds_format)
from clist.utils import create_contest_problem_discussions, update_problems, update_writers
from logify.models import EventLog, EventStatus
from notification.models import NotificationMessage, Subscription
from notification.utils import compose_message_by_problems, compose_message_by_submissions, send_messages
from pyclist.decorators import analyze_db_queries
from ranking.management.commands.parse_accounts_infos import rename_account
from ranking.management.modules.common import REQ, UNCHANGED
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException, ProxyLimitReached
from ranking.models import Account, AccountRenaming, Module, Stage, Statistics
from ranking.utils import account_update_contest_additions, update_stage
from ranking.views import update_standings_socket
from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.countrier import Countrier
from utils.logger import suppress_db_logging_context
from utils.mathutils import min_with_none
from utils.timetools import parse_datetime
from utils.tools import sum_data
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
            context = {
                'type': 'update_statistics',
                'raw': str(progress_bar),
            }
        else:
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        parser.add_argument('--without-set-coder-problems', action='store_true', default=False)
        parser.add_argument('--without-calculate-problem-rating', action='store_true', default=False)
        parser.add_argument('--without-calculate-rating-prediction', action='store_true', default=False)
        parser.add_argument('--without-stage', action='store_true', default=False, help='Without update stage contests')
        parser.add_argument('--without-subscriptions', action='store_true', default=False, help='Without subscriptions')
        parser.add_argument('--contest-id', '-cid', help='Contest id')
        parser.add_argument('--no-update-problems', action='store_true', default=False, help='No update problems')
        parser.add_argument('--is-rated', action='store_true', default=False, help='Contest is rated')
        parser.add_argument('--after', type=str, help='Events after date')
        parser.add_argument('--for-account', type=str, help='Events for account')
        parser.add_argument('--ignore-stage', action='store_true', default=False, help='Ignore stage')
        parser.add_argument('--disabled', action='store_true', default=False, help='Disabled module only')
        parser.add_argument('--without-delete-statistics', action='store_true')
        parser.add_argument('--allow-delete-statistics', action='store_true')
        parser.add_argument('--clear-submissions-info', action='store_true')
        parser.add_argument('--split-by-resource', action='store_true', help='Separately for each resource')

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
        specific_users=None,
        with_stats=True,
        update_without_new_rating=None,
        force_problems=False,
        force_socket=False,
        without_n_statistics=False,
        contest_id=None,
        query=None,
        without_set_coder_problems=False,
        without_calculate_problem_rating=False,
        without_calculate_rating_prediction=False,
        without_stage=False,
        without_subscriptions=False,
        no_update_problems=None,
        is_rated=None,
        for_account=None,
        ignore_stage=None,
        with_reparse=None,
        enabled=True,
        without_delete_statistics=None,
        allow_delete_statistics=None,
        clear_submissions_info=None,
        split_by_resource=None,
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
        stage_delay = timedelta(days=1)

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
                        | Q(has_unlimited_statistics=True)
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
                    in_range_contests = contests.filter(before_end_limit_query & after_start_query)

                    inherit_stage_query = Q(stage__isnull=True, info___inherit_stage=True, start_time__lt=now)
                    inherit_contests = contests.filter(before_end_limit_query & inherit_stage_query)

                    contests_query = (
                        Q(pk__in=parsed_contests)
                        | Q(pk__in=in_range_contests)
                        | Q(pk__in=inherit_contests)
                    )
                    contests = Contest.objects.filter(contests_query).filter(stage__isnull=True)
                contests = contests.filter(resource__module__enable=enabled)
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
            contests = contests.filter(statistics__account__key=for_account, statistics__skip_in_stats=False)

        if limit:
            contests = contests.order_by((limit_order or '-start_time').strip(), '-id')[:limit]

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
        n_inherited_medals = 0
        progress_bar = tqdm(contests)
        stages_ids = []

        resources = {contest.resource for contest in contests}
        if split_by_resource:
            queue = django_rq.get_queue('parse_statistics')
            for resource in resources:
                resource_host = resource.host.split('/')[0]
                job_id = f'parse_statistics_{resource_host}'

                job = queue.fetch_job(job_id)
                if not job or job.is_finished or job.is_failed:
                    kwargs = {'resources': [resource.host]}
                    job = queue.enqueue(call_command, 'parse_statistic', **kwargs, job_id=job_id)
                    self.logger.info(f'Added {resource} parse_statistics job to queue: job = {job}')
                else:
                    self.logger.info(f'{resource} parse_statistics job already in queue: job = {job}')
            return

        if len(resources) == 1 and len(contests) > 3:
            resource_event_log = EventLog.objects.create(name='parse_statistic',
                                                         related=contests[0].resource,
                                                         status=EventStatus.IN_PROGRESS)
        else:
            resource_event_log = None

        processed_group = set()
        error_counter = defaultdict(int)
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
                contest.statistic_timing = now + stage_delay
                contest.save(update_fields=['statistic_timing'])
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
            event_log = EventLog.objects.create(name='parse_statistic',
                                                related=contest,
                                                status=EventStatus.IN_PROGRESS)
            contest_log_counter = defaultdict(int)

            try:
                now = timezone_now()
                is_coming = now < contest.start_time
                is_archive_contest = (max(contest.created, contest.end_time) + timedelta(days=30) < now and
                                      contest.parsed_time)
                is_fast_reparse = contest.parsed_time and now - contest.parsed_time < timedelta(minutes=5)

                with_subscription = not without_subscriptions and not is_archive_contest and with_stats
                with_upsolving_subscription = not without_subscriptions and not resource.has_upsolving
                prefetch_subscribed_coders = Prefetch('coders', queryset=Coder.objects.filter(n_subscribers__gt=0),
                                                      to_attr='subscribed_coders')
                subscription_top_n = None
                subscription_first_ac = None
                if with_subscription:
                    subscriptions = Subscription.for_statistics.filter(
                        (Q(resource__isnull=True) | Q(resource=resource)) &
                        (Q(contest__isnull=True) | Q(contest=contest))
                    )
                    subscription_top_n = subscriptions.aggregate(n=Max('top_n'))['n']
                    subscription_first_ac = subscriptions.filter(with_first_accepted=True).exists()

                plugin = resource.plugin.Statistic(contest=contest)

                with transaction.atomic():
                    _ = Contest.objects.select_for_update().get(pk=contest.pk)

                    statistics_users = copy.deepcopy(specific_users)
                    if resource.has_standings_renamed_account and specific_users:
                        renamings = AccountRenaming.objects.filter(resource=resource, old_key__in=specific_users)
                        renamings = renamings.values_list('new_key', flat=True)
                        statistics_users.extend(renamings)

                    with REQ:
                        statistics_by_key = {}
                        more_statistics_by_key = {}
                        statistics_to_delete = set()
                        has_statistics = False
                        if not no_update_results:
                            statistics = Statistics.objects.filter(contest=contest).select_related('account')
                            if specific_users:
                                statistics = statistics.filter(account__key__in=statistics_users)
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
                                statistics_to_delete.add(s.pk)
                        if clear_submissions_info:
                            contest.submissions_info = {}
                            contest.save(update_fields=['submissions_info'])
                        standings = plugin.get_standings(users=copy.deepcopy(specific_users),
                                                         statistics=copy.deepcopy(statistics_by_key),
                                                         more_statistics=copy.deepcopy(more_statistics_by_key))
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
                                        statistics_to_delete.remove(stat['pk'])
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
                                        statistics_to_delete.remove(stat['pk'])
                                        contest_log_counter['skip_no_update'] += 1
                                        result.pop(member)

                        keep_results = standings.pop('keep_results', False)
                        skip_instead_update = standings.pop('keep_results_to_skip', False)
                        parsed_percentage = standings.pop('parsed_percentage', None)
                        if keep_results or skip_instead_update:
                            reset_place = parsed_percentage and not contest.parsed_percentage
                            reset_place_ids = set()
                            result = standings.setdefault('result', {})
                            for member, row in statistics_by_key.items():
                                if member in result:
                                    continue
                                more_stat = more_statistics_by_key[member]
                                pk = more_stat['pk']
                                if pk in statistics_to_delete:
                                    statistics_to_delete.remove(pk)
                                    row = copy.deepcopy(row)
                                    row['member'] = member
                                    if skip_instead_update:
                                        if more_stat['place']:
                                            row['solving'] = more_stat['score']
                                            row['_last_place'] = more_stat['place']
                                            row['place'] = None
                                            more_stat['place'] = None
                                        row['_no_update_n_contests'] = True
                                        contest_log_counter['skip_instead_update'] += 1
                                    else:
                                        row['_skip_update'] = True
                                        contest_log_counter['skip_update'] += 1
                                    result[member] = row
                                    if reset_place:
                                        row.pop('place', None)
                                        reset_place_ids.add(pk)
                            if reset_place_ids:
                                Statistics.objects.filter(pk__in=reset_place_ids).update(place=None, place_as_int=None)

                        if get_item(resource, 'info.standings.skip_not_solving'):
                            result = standings.setdefault('result', {})
                            for member in list(result):
                                row = result[member]
                                if not row.get('solving'):
                                    contest_log_counter['skip_not_solving'] += 1
                                    result.pop(member)

                        if get_item(resource, 'info.standings.skip_country'):
                            result = standings.setdefault('result', {})
                            for row in result.values():
                                if 'country' in row:
                                    row['__country'] = row.pop('country')
                                    contest_log_counter['skip_country'] += 1

                        if get_item(resource, 'info.standings.skip_rating'):
                            result = standings.setdefault('result', {})
                            for row in result.values():
                                for field in Resource.RATING_FIELDS:
                                    if field in row:
                                        row[f'__{field}'] = row.pop(field)
                                        contest_log_counter['skip_rating'] += 1

                        for key, more_stat in more_statistics_by_key.items():
                            statistics_by_key[key].update(more_stat)

                    update_fields = []
                    for field, attr in (
                        ('url', 'standings_url'),
                        ('contest_url', 'url'),
                        ('title', 'title'),
                        ('invisible', 'invisible'),
                        ('duration_in_secs', 'duration_in_secs'),
                        ('kind', 'kind'),
                        ('standings_kind', 'standings_kind'),
                        ('is_rated', 'is_rated'),
                        ('has_hidden_results', 'has_hidden_results'),
                        ('submissions_info', 'submissions_info'),
                    ):
                        if field in standings and standings[field] != getattr(contest, attr):
                            setattr(contest, attr, standings[field])
                            update_fields.append(attr)
                    if parsed_percentage is not None:
                        contest.parsed_percentage = parsed_percentage if parsed_percentage < 100 else None
                        if contest.parsed_percentage:
                            self.logger.info(f'parsed percentage = {contest.parsed_percentage}')
                        update_fields.append('parsed_percentage')
                    if update_fields:
                        contest.save(update_fields=update_fields)

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

                    if raw_info := standings.pop('raw_info', None):
                        contest_raw_info = copy.deepcopy(contest.raw_info)
                        outdated_info = contest_raw_info.pop('_outdated', {})
                        if raw_info != contest_raw_info:
                            for k, v in raw_info.items():
                                if v == contest_raw_info.get(k):
                                    contest_raw_info.pop(k, None)
                            outdated_info.update(contest_raw_info)
                            contest_raw_info.update(raw_info)
                            if outdated_info:
                                contest_raw_info['_outdated'] = outdated_info
                            contest.raw_info = contest_raw_info
                            contest.save(update_fields=['raw_info'])

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
                                    result[new_key]['_old_key'] = result[new_key]['member']
                                    result[new_key]['member'] = new_key
                                    result[new_key]['_no_update_name'] = True
                                    result[new_key].pop('info', None)

                    require_statistics_update = standings.pop('require_statistics_update', False)
                    if require_statistics_update:
                        contest.require_statistics_update()

                    if standings_counters := standings.pop('counters', {}):
                        contest_log_counter = sum_data(contest_log_counter, standings_counters)

                    parse_info = contest.info.get('parse', {})
                    resource_statistics = resource.info.get('statistics') or {}
                    wait_rating = resource_statistics.get('wait_rating', {})
                    has_hidden = standings.pop('has_hidden', False)
                    with_link_accounts = standings.pop('link_accounts', False)
                    is_major_kind = resource.is_major_kind(contest.kind)
                    custom_fields_types = standings.pop('fields_types', {})
                    guess_standings_kinds = ['icpc', 'scoring']
                    standings_kinds = set(guess_standings_kinds)
                    has_more_solving = bool(contest.info.get('_more_solving'))
                    updated_statistics_ids = list()
                    contest_timeline = contest.get_timeline_info()
                    lazy_fetch_accounts = standings.pop('lazy_fetch_accounts', False)
                    has_problem_stats = False

                    results = []
                    if result or specific_users:
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
                                nonlocal last_activity, total_problems_solving, has_problem_stats, has_hidden

                                problems = r.get('problems', {})

                                is_new = ('team_id' not in r or r['team_id'] not in teams_viewed) and not skip_result
                                if 'team_id' in r:
                                    teams_viewed.add(r['team_id'])

                                solved = {'solving': 0}
                                if is_new:
                                    if r.get('division'):
                                        n_statistics[r.get('division')] += 1
                                    n_statistics['__total__'] += 1

                                default_full_score = (
                                    contest.info.get('default_problem_full_score')
                                    or resource_statistics.get('default_problem_full_score')
                                )

                                for k, v in problems.items():
                                    p = d_problems
                                    standings_p = standings_problems
                                    if standings_p and 'division' in standings_p:
                                        if not r.get('division'):
                                            continue
                                        p = p.setdefault(r['division'], {})
                                        standings_p = standings_p.get(r['division'], [])
                                    p = p.setdefault(k, {})

                                    has_result = 'result' in v
                                    result_str = str(v.get('result'))
                                    result_num = as_number(v.get('result'), force=True)
                                    is_score = is_scoring_result(v)

                                    if default_full_score and is_score:
                                        if default_full_score == 'max':
                                            if result_num is not None:
                                                p['max_score'] = max(p.get('max_score', float('-inf')), result_num)
                                        elif default_full_score == 'min':
                                            if result_num is not None:
                                                p['min_score'] = min(p.get('min_score', float('inf')), result_num)
                                        else:
                                            if 'full_score' not in p:
                                                for i in standings_p:
                                                    if get_problem_key(i) == k and 'full_score' in i:
                                                        p['full_score'] = i['full_score']
                                                        break
                                                else:
                                                    p['full_score'] = default_full_score
                                            if has_result:
                                                if 'partial' not in v and p['full_score'] - result_num > EPS:
                                                    v['partial'] = True
                                                if not v.get('partial'):
                                                    solved['solving'] += 1
                                            if u := v.get('upsolving'):
                                                upsolving_num = as_number(u['result'], default=0)
                                                if 'partial' not in u and p['full_score'] - upsolving_num > EPS:
                                                    u['partial'] = True
                                                if not u.get('partial'):
                                                    solved.setdefault('upsolving', 0)
                                                    solved['upsolving'] += 1

                                    if 'result' not in v:
                                        continue

                                    is_hidden_result = is_hidden(v)
                                    has_hidden |= is_hidden_result

                                    if result_str and result_str[0] not in '+-?':
                                        standings_kinds.discard('icpc')
                                    if result_str and result_num is None:
                                        standings_kinds.discard('scoring')

                                    scored = get_result_score(result_str)
                                    total_problems_solving += scored
                                    ac = is_solved(v)

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
                                    elif is_hidden_result:
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

                        if (
                            len(standings_kinds) == 1 and
                            (not contest.standings_kind or contest.standings_kind in guess_standings_kinds) and
                            contest.standings_kind != (standings_kind := standings_kinds.pop())
                        ):
                            contest.standings_kind = standings_kind
                            contest.save(update_fields=['standings_kind'])

                        if has_hidden and not contest.has_hidden_results and is_archive_contest:
                            raise ExceptionParseStandings('archive contest has hidden results')
                        if has_hidden != contest.has_hidden_results and 'has_hidden_results' not in standings:
                            contest.has_hidden_results = has_hidden
                            contest.save(update_fields=['has_hidden_results'])

                        if not lazy_fetch_accounts:
                            members = [r['member'] for r in results]
                            accounts = resource.account_set
                            if with_subscription:
                                accounts = accounts.prefetch_related(prefetch_subscribed_coders)
                            accounts = accounts.filter(key__in=members)
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
                                account = Account.objects
                                if with_subscription:
                                    account = account.prefetch_related(prefetch_subscribed_coders)
                                account, account_created = account.get_or_create(resource=resource, key=member)
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
                                    contest_log_counter['renamed_accounts'] += 1

                            result_submissions = r.pop('submissions', [])
                            if contest.has_submissions and not result_submissions:
                                self.logger.warning(f'Not found submissions for account = {account}')

                            result_upsolving_submissions = r.pop('upsolving_submissions', [])
                            if result_upsolving_submissions:
                                contest_log_counter['n_upsolving_submissions'] += len(result_upsolving_submissions)

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
                                    specific_users
                                ):
                                    return

                                nonlocal n_account_time_update
                                no_rating = with_stats and (
                                    ('new_rating' in stat) + ('rating_change' in stat) + ('old_rating' in stat) < 2
                                )

                                updated_delta = resource_statistics.get('account_updated_delta', {'hours': 12})
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
                                            addition_update = user_info.get('contest_addition_update') or params.get('update') or {}  # noqa
                                            if not isinstance(field, (list, tuple)):
                                                field = [field]
                                            user_info_has_rating[division] = False
                                            for f in field:
                                                if getattr(contest, f) in addition_update:
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
                                    account.save(update_fields=['info'])

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
                                    update_fields = ['info']
                                    if 'rating' in account_info and not is_major_kind:
                                        account_info.pop('rating')
                                    if 'name' in account_info:
                                        name = account_info.pop('name')
                                        name = name if name and name != account.key else None
                                        if account.name != name:
                                            account.name = name
                                            update_fields.append('name')
                                    if 'deleted' in account_info:
                                        account.deleted = account_info.pop('deleted')
                                        update_fields.append('deleted')
                                    account.info.update(account_info)
                                    account.save(update_fields=update_fields)

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
                                    if k not in p:
                                        continue
                                    p = p.get(k, {})
                                    if 'first_ac' in p and member in p['first_ac']['accounts']:
                                        v['first_ac'] = True
                                    if p.get('n_teams') and not p.get('n_accepted') and is_hidden(v):
                                        v['try_first_ac'] = True
                                    else:
                                        v.pop('try_first_ac', None)

                            def update_statistic_stats():
                                problem_stats = get_statistic_stats(r)
                                r.update(problem_stats)

                            def get_addition():
                                place = r.pop('place', None)
                                defaults = {
                                    'resource': resource,
                                    'place': place,
                                    'place_as_int': place if place == UNCHANGED else get_number_from_str(place),
                                    'solving': r.pop('solving', 0),
                                    'upsolving': r.pop('upsolving', None),
                                    'total_solving': r.pop('total_solving', 0),
                                    'n_solved': r.pop('n_solved', 0),
                                    'n_upsolved': r.pop('n_upsolved', None),
                                    'n_total_solved': r.pop('n_total_solved', 0),
                                    'n_first_ac': r.pop('n_first_ac', 0),
                                    'penalty': as_number(r.get('penalty'), force=True),
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

                                rating_time = min(contest.end_time, now)
                                if (
                                    is_major_kind
                                    and 'new_rating' in addition
                                    and (
                                        'rating' not in account.info
                                        or account.rating_update_time is None
                                        or account.rating_update_time < rating_time
                                    )
                                ):
                                    account.info['rating'] = addition['new_rating']
                                    account.rating_update_time = rating_time
                                    account.save(update_fields=['info', 'rating_update_time'])

                                try_calculate_time = contest.calculate_time or (
                                    contest.start_time <= now < contest.end_time and
                                    not get_item(resource, 'info.parse.no_calculate_time') and
                                    contest.full_duration < resource.module.long_contest_idle and
                                    'penalty' in fields_set and
                                    is_fast_reparse
                                )

                                if not try_calculate_time:
                                    defaults['addition'] = addition

                                return defaults, addition, try_calculate_time

                            def update_after_update_or_create(statistic, created, addition, try_calculate_time):
                                updates = {}
                                updates['has_first_ac'] = False
                                updated_problems = updates.setdefault('problems', [])
                                problems = r.get('problems', {})

                                if not created:
                                    nonlocal calculate_time
                                    statistics_to_delete.discard(statistic.pk)

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

                                if force_socket:
                                    updated_statistics_ids.append(statistic.pk)

                                previous_problems = stat.get('problems', {})
                                for k, problem in problems.items():
                                    verdict = problem.get('verdict')
                                    previous_problem = previous_problems.get(k, {})
                                    previous_verdict = previous_problem.get('verdict')
                                    same_result = problem.get('result') == previous_problem.get('result')
                                    same_verdict = not verdict or not previous_verdict or verdict == previous_verdict
                                    same_verdict |= is_solved(problem)
                                    if same_result and same_verdict:
                                        continue
                                    if not same_result and problem.get('first_ac'):
                                        updates['has_first_ac'] = True
                                    updated_problems.append(k)
                                    if statistic.pk in updated_statistics_ids:
                                        continue
                                    contest_log_counter['updated_statistics_problem'] += 1
                                    updated_statistics_ids.append(statistic.pk)

                                for field, lhs, rhs in (
                                    ('place', str(statistic.place), str(stat.get('place'))),
                                    ('score', statistic.solving, stat.get('score')),
                                ):
                                    if lhs != rhs and statistic.pk not in updated_statistics_ids:
                                        contest_log_counter[f'updated_statistics_{field}'] += 1
                                        updated_statistics_ids.append(statistic.pk)

                                if try_calculate_time:
                                    statistic.addition = addition
                                    statistic.save()
                                return updates

                            @suppress_db_logging_context()
                            def update_submissions(statistic, result_submissions):
                                if not result_submissions:
                                    return

                                if not contest.has_submissions:
                                    contest.has_submissions = True
                                    contest.save(update_fields=['has_submissions'])

                                statistic_problems = statistic.addition.get('problems', {})
                                updated_submission_problems = False
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
                                                updated_submission_problems = True
                                if update_problems_values(statistic.addition):
                                    updated_submission_problems = True
                                if updated_submission_problems:
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
                                for problem_field, field, contest_field in settings.PROBLEM_STATISTIC_FIELDS:
                                    values = set()
                                    for problem in problems.values():
                                        value = problem.get(problem_field)
                                        if value:
                                            problems_values[contest_field].add(value)
                                            values.add(value)
                                    if field not in addition and values:
                                        addition[field] = list(values)
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

                            def process_subscriptions(statistic, updates):
                                if skip_result or not with_subscription:
                                    return
                                if addition.get('_skip_subscription') or not updates['problems']:
                                    return

                                with_top_n = (subscription_top_n and statistic.place_as_int and
                                              statistic.place_as_int <= subscription_top_n)
                                with_first_ac = updates['has_first_ac'] and subscription_first_ac
                                subscribed_coders = getattr(account, 'subscribed_coders', None)
                                if (
                                    not account.n_subscribers and
                                    not subscribed_coders and
                                    not with_top_n and
                                    not with_first_ac
                                ):
                                    return

                                kwargs = {
                                    'problem_shorts': updates['problems'],
                                    'statistic': statistic,
                                    'previous_addition': stat,
                                    'contest_or_problems': standings_problems,
                                }
                                subscription_message = compose_message_by_problems(**kwargs)

                                subscriptions_filter = Q()
                                if account.n_subscribers:
                                    subscriptions_filter |= Q(accounts=account)
                                if subscribed_coders:
                                    subscriptions_filter |= Q(coders__in=subscribed_coders)
                                if with_top_n:
                                    subscriptions_filter |= Q(top_n__gte=statistic.place_as_int)
                                if with_first_ac:
                                    subscriptions_filter |= Q(with_first_accepted=True)
                                subscriptions_filter = (
                                    subscriptions_filter
                                    & (Q(resource__isnull=True) | Q(resource=resource))
                                    & (Q(contest__isnull=True) | Q(contest=contest))
                                )
                                subscriptions = Subscription.for_statistics.filter(subscriptions_filter)
                                already_sent = set()
                                for subscription in subscriptions:
                                    if subscription.notification_key in already_sent:
                                        continue
                                    already_sent.add(subscription.notification_key)

                                    message = compose_message_by_problems(
                                        subscription=subscription,
                                        general_message=subscription_message,
                                        **kwargs,
                                    )
                                    subscription.send(message=message, contest=contest)
                                    contest_log_counter['statistics_subscription'] += 1

                            def process_upsolving_subscriptions(submissions):
                                if not submissions or not with_upsolving_subscription:
                                    return
                                subscribed_coders = getattr(account, 'subscribed_coders', None)
                                if not account.n_subscribers and not subscribed_coders:
                                    return

                                subscriptions_filter = Q()
                                if account.n_subscribers:
                                    subscriptions_filter |= Q(accounts=account)
                                if subscribed_coders:
                                    subscriptions_filter |= Q(coders__in=subscribed_coders)
                                subscriptions_filter = (
                                    subscriptions_filter
                                    & (Q(resource__isnull=True) | Q(resource=resource))
                                    & (Q(contest__isnull=True) | Q(contest=contest))
                                )
                                upsolving_subscriptions = Subscription.for_upsolving.filter(subscriptions_filter)

                                processed = set()
                                for subscription in upsolving_subscriptions:
                                    message = compose_message_by_submissions(
                                        resource, account, submissions,
                                        cache=processed,
                                        subscription=subscription,
                                    )
                                    if not message:
                                        continue
                                    subscription.send(message=message)
                                    contest_log_counter['statistics_subscription'] += 1

                            update_addition_fields()
                            update_account_time()
                            update_account_info()
                            update_stat_info()
                            update_problems_values(r)
                            if not specific_users:
                                update_problems_first_ac()
                            update_statistic_stats()
                            defaults, addition, try_calculate_time = get_addition()

                            statistics_objects = Statistics.saved_objects
                            statistics_objects = statistics_objects.select_related('account', 'contest', 'resource')
                            statistic, statistic_created = statistics_objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )

                            n_statistics_total += 1
                            n_statistics_created += statistic_created
                            contest_log_counter['statistics_total'] += 1
                            if statistic_created:
                                contest_log_counter['statistics_created'] += 1

                            updates = update_after_update_or_create(statistic, statistic_created, addition,
                                                                    try_calculate_time)

                            update_submissions(statistic, result_submissions)

                            if with_link_accounts:
                                link_account(statistic)

                            if contest.set_matched_coders_to_members:
                                set_matched_coders_to_members(statistic)

                            process_subscriptions(statistic, updates)
                            process_upsolving_subscriptions(result_upsolving_submissions)

                        if not specific_users:
                            for field, values in problems_values.items():
                                values = list(sorted(values))
                                if canonize(values) != canonize(contest.info.get(field)):
                                    contest.info[field] = values
                            for _, field, contest_field in settings.PROBLEM_STATISTIC_FIELDS:
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

                            if (
                                statistics_to_delete and
                                not without_delete_statistics and
                                (first_deleted := Statistics.objects.filter(pk__in=statistics_to_delete).first())
                            ):
                                self.logger.info(f'First deleted: {first_deleted}')
                                prefix_size = 5
                                prefix_deleted = list(statistics_to_delete)[:prefix_size]
                                prefix_deleted = ', '.join(map(str, prefix_deleted))
                                if len(statistics_to_delete) > prefix_size:
                                    prefix_deleted += ', ...'
                                self.logger.info(f'{len(statistics_to_delete)} statistics to delete: {prefix_deleted}')

                                if is_archive_contest and not allow_delete_statistics:
                                    raise ExceptionParseStandings(
                                        f'archive contest has {len(statistics_to_delete)} statistics to delete')

                                delete_info = Statistics.objects.filter(pk__in=statistics_to_delete).delete()
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
                                    n_problems = dict()
                                    for d, ps in standings_problems['division'].items():
                                        n_problems[d] = len(ps)
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
                                    standings_problems['n_problems'] = n_problems
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
                                    if force_problems:
                                        create_contest_problem_discussions(contest)

                            contest.save()

                            if to_update_socket:
                                update_standings_socket(contest, updated_statistics_ids)

                            progress_bar.set_postfix(n_fields=len(fields), n_updated=len(updated_statistics_ids))
                    else:
                        if standings_problems is not None and standings_problems and not no_update_problems:
                            standings_problems = plugin.merge_dict(standings_problems, contest.info.get('problems'))
                            update_problems(contest, problems=standings_problems, force=force_problems)

                    if contest_log_counter.get('statistics_subscription'):
                        send_messages()

                    if not specific_users:
                        timing_delta = None
                        if contest.full_duration < resource.module.long_contest_idle:
                            timing_delta = standings.get('timing_statistic_delta', timing_delta)
                            if now < contest.end_time:
                                timing_delta = parse_info.get('timing_statistic_delta', timing_delta)
                        if updated_statistics_ids and contest.end_time < now < contest.end_time + timedelta(hours=1):
                            timing_delta = timing_delta or timedelta(minutes=20)
                        if contest.has_hidden_results and contest.end_time < now < contest.end_time + timedelta(days=1):
                            timing_delta = timing_delta or timedelta(minutes=60)
                        if wait_rating and not has_statistics and results and 'days' in wait_rating:
                            timing_delta = timing_delta or timedelta(days=wait_rating['days']) / 10
                        timing_delta = timedelta(**timing_delta) if isinstance(timing_delta, dict) else timing_delta
                        if contest.has_unlimited_statistics and contest.end_time < now:
                            last_action_time = contest.submissions_info.get('last_upsolving_submission_time',
                                                                            contest.end_time)
                            last_action_time = arrow.get(last_action_time).datetime
                            last_action_delta = max(now - last_action_time, timedelta(hours=1))
                            timing_delta = min_with_none(timing_delta, last_action_delta)
                        if timing_delta is not None:
                            self.logger.info(f'Statistic timing delta = {timing_delta}')
                            contest.info['_timing_statistic_delta_seconds'] = timing_delta.total_seconds()
                        else:
                            contest.info.pop('_timing_statistic_delta_seconds', None)
                        if not require_statistics_update:
                            contest.statistics_update_done()
                        contest.save()
                    else:
                        without_calculate_rating_prediction = True

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
                            contest.save(update_fields=['url'])
                        elif action == 'skip':
                            contest.parsed_time = now
                            contest.save(update_fields=['parsed_time'])

                if not contest.statistics_update_required and contest.pk:
                    if resource.rating_prediction and not without_calculate_rating_prediction and not specific_users:
                        self.logger.info(f'Calculate rating prediction for contest = {contest}')
                        call_command('calculate_rating_prediction', contest=contest.pk)
                        contest.refresh_from_db()
                        n_calculated_rating_prediction += 1

                    if (
                        resource.has_problem_rating and contest.is_finalized() and not without_calculate_problem_rating
                        and not specific_users
                    ):
                        self.logger.info(f'Calculate problem rating for contest = {contest}')
                        call_command('calculate_problem_rating', contest=contest.pk, force=force_problems)
                        contest.refresh_from_db()
                        n_calculated_problem_rating += 1

                    if contest.is_finalized():
                        related_contests = [contest]
                        for related in contest.related_set.select_related('resource', 'related').all():
                            related_contests.append(related)
                        for orig_contest in related_contests:
                            related_contest = orig_contest.related
                            if not related_contest:
                                continue
                            if not orig_contest.resource.has_inherit_medals_to_related:
                                continue
                            if not orig_contest.is_finalized():
                                continue
                            if not orig_contest.with_medals or related_contest.with_medals:
                                continue
                            self.logger.info(f'Inherit medals to related contest = {related_contest}'
                                             f', from contest = {orig_contest}')
                            related_contest.inherit_medals(orig_contest)
                            n_inherited_medals += 1

                    if not without_set_coder_problems:
                        if specific_users:
                            users_qs = Account.objects.filter(resource=resource, key__in=specific_users)
                            users_coders = Coder.objects.filter(Exists(users_qs.filter(pk=OuterRef('account'))))
                            users_coders = users_coders.values_list('username', flat=True)
                            if users_coders:
                                self.logger.info(f'Set coder problems for contest = {contest}'
                                                 f', coders = {users_coders}')
                                call_command('set_coder_problems', contest=contest.pk, coders=users_coders)
                        else:
                            self.logger.info(f'Set coder problems for contest = {contest}')
                            call_command('set_coder_problems', contest=contest.pk)

                if has_standings_result:
                    count += 1
                parsed = True
                event_status = EventStatus.COMPLETED
            except (ExceptionParseStandings, InitModuleException, ProxyLimitReached) as e:
                event_status = EventStatus.WARNING
                if with_reparse and isinstance(e, ExceptionParseStandings):
                    contest.statistics_update_done()
                exception_error = str(e)
                self.logger.warning(f'parse_statistic exception: {e}')
                progress_bar.set_postfix(exception=str(e), cid=str(contest.pk))
            except Exception as e:
                event_status = EventStatus.FAILED
                exception_error = str(e)
                error_counter[str(e)] += 1
                self.logger.debug(colored_format_exc())
                self.logger.error(f'parse_statistic exception: {e}')
                has_error = True
                if stop_on_error:
                    print(colored_format_exc())

            if not specific_users:
                module = resource.module
                delay = module.max_delay_after_end
                if contest.statistics_update_required or contest.end_time < now or not module.long_contest_divider:
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

            messages = []
            if contest_log_counter:
                messages += [f'log_counter = {dict(contest_log_counter)}']
            event_log.update(status=event_status, message='\n\n'.join(messages), error=exception_error)
            if specific_users:
                event_log.delete()
            self.logger.info(f'log_counter = {dict(contest_log_counter)}')
            channel_layer_handler.send_done(done=parsed)
        if error_counter:
            self.logger.info(f'error_counter = {dict(error_counter)}')

        @lru_cache(maxsize=None)
        def advanced_update_stage(stage):
            exclude_stages = stage.score_params.get('advances', {}).get('exclude_stages', [])
            ret = stage.pk in stages_ids
            if exclude_stages:
                for s in Stage.objects.filter(pk__in=exclude_stages):
                    if advanced_update_stage(s):
                        ret = True
            if ret:
                try:
                    event_log = EventLog.objects.create(name='parse_statistic',
                                                        related=stage,
                                                        status=EventStatus.IN_PROGRESS)
                    channel_layer_handler.set_contest(stage.contest)
                    stage.contest.statistic_timing = now + stage_delay
                    stage.contest.save(update_fields=['statistic_timing'])
                    update_stage(stage)
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
                    advanced_update_stage(stage)

        if resource_event_log:
            resource_event_log.delete()
        progress_bar.close()

        self.logger.info(f'Number of parsed contests: {count} of {total}')
        if n_calculated_problem_rating:
            self.logger.info(f'Number of calculate rating problem: {n_calculated_problem_rating} of {total}')
        if n_calculated_rating_prediction:
            self.logger.info(f'Number of calculate rating prediction: {n_calculated_rating_prediction} of {total}')
        if n_inherited_medals:
            self.logger.info(f'Number of inherited medals: {n_inherited_medals} of {total}')
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
            resources = Resource.get(args.resources)
            contests = Contest.objects.filter(resource__module__resource__in=resources)
        else:
            has_module = Module.objects.filter(resource_id=OuterRef('resource__pk'))
            contests = Contest.objects.annotate(has_module=Exists(has_module)).filter(has_module=True)
        contests = contests.order_by('start_time')

        if args.only_new:
            has_statistics = Statistics.objects.filter(contest_id=OuterRef('pk'))
            contests = contests.annotate(has_statistics=Exists(has_statistics)).filter(has_statistics=False)
            contests = contests.filter(Q(n_problems__isnull=True) | Q(n_problems=0))
            contests = contests.filter(parsed_time__isnull=True)

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
            contests = contests.filter(statistics_update_required=True)

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
            specific_users=args.users,
            with_stats=not args.no_stats,
            update_without_new_rating=args.update_without_new_rating,
            force_problems=args.force_problems,
            force_socket=args.force_socket,
            without_n_statistics=args.without_n_statistics,
            contest_id=args.contest_id,
            query=args.query,
            without_set_coder_problems=args.without_set_coder_problems,
            without_calculate_problem_rating=args.without_calculate_problem_rating,
            without_calculate_rating_prediction=args.without_calculate_rating_prediction,
            without_stage=args.without_stage,
            without_subscriptions=args.without_subscriptions,
            no_update_problems=args.no_update_problems,
            is_rated=args.is_rated,
            for_account=args.for_account,
            ignore_stage=args.ignore_stage,
            with_reparse=args.reparse,
            enabled=not args.disabled,
            without_delete_statistics=args.without_delete_statistics,
            allow_delete_statistics=args.allow_delete_statistics,
            clear_submissions_info=args.clear_submissions_info,
            split_by_resource=args.split_by_resource,
        )
