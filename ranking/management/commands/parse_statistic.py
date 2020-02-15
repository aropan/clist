#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import json
from html import unescape
from collections import OrderedDict
from random import shuffle
from tqdm import tqdm
from attrdict import AttrDict
from datetime import timedelta
from logging import getLogger
from traceback import format_exc

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, F, OuterRef, Exists

from ranking.models import Statistics, Account, Stage, Module
from clist.models import Contest, Resource, TimingContest
from ranking.management.modules.excepts import ExceptionParseStandings, InitModuleException
from ranking.management.commands.countrier import Countrier


class Command(BaseCommand):
    help = 'Parsing statistics'
    SUCCESS_TIME_DELTA_ = timedelta(days=7)
    UNSUCCESS_TIME_DELTA_ = timedelta(days=1)

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.statistic')

    def add_arguments(self, parser):
        parser.add_argument('-d', '--days', type=int, help='how previous days for update')
        parser.add_argument('-f', '--freshness_days', type=int, help='how previous days skip by modified date')
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-e', '--event', help='regex event name')
        parser.add_argument('-l', '--limit', type=int, help='limit count parse contest by resource', default=None)
        parser.add_argument('-c', '--no-check-timing', action='store_true', help='no check timing statistic')
        parser.add_argument('-o', '--only-new', action='store_true', default=False, help='parse without statistics')
        parser.add_argument('-s', '--stop-on-error', action='store_true', default=False, help='stop on exception')
        parser.add_argument('--random-order', action='store_true', default=False, help='Random order contests')
        parser.add_argument('--no-update-results', action='store_true', default=False, help='Do not update results')

    @staticmethod
    def _get_plugin(module):
        sys.path.append(os.path.dirname(module.path))
        return __import__(module.path.replace('/', '.'), fromlist=['Statistic'])

    @staticmethod
    def _canonize(data):
        return json.dumps(data, sort_keys=True)

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
        limit_duration_in_secs=7 * 60 * 60,  # 7 hours
    ):
        now = timezone.now()

        if with_check:
            if previous_days is not None:
                contests = contests.filter(end_time__gt=now - timedelta(days=previous_days), end_time__lt=now)
            else:
                contests = contests.filter(Q(timing__statistic__isnull=True) | Q(timing__statistic__lt=now))
                started = contests.filter(start_time__lt=now, end_time__gt=now, statistics__isnull=False)

                query = Q()
                query &= Q(end_time__gt=now - F('resource__module__max_delay_after_end'))
                query &= Q(end_time__lt=now - F('resource__module__min_delay_after_end'))
                ended = contests.filter(query)

                contests = started.union(ended)
                contests = contests.distinct('id')
        else:
            contests = contests.filter(Q(end_time__lt=now - F('resource__module__min_delay_after_end')))

        if freshness_days is not None:
            contests = contests.filter(updated__lt=now - timedelta(days=freshness_days))

        if limit:
            contests = contests.order_by('-start_time')[:limit]

        with transaction.atomic():
            for c in contests:
                module = c.resource.module
                delay_on_success = module.delay_on_success or module.max_delay_after_end
                if now < c.end_time:
                    if c.duration_in_secs <= limit_duration_in_secs:
                        delay_on_success = timedelta(minutes=0)
                    elif c.end_time < now + delay_on_success:
                        delay_on_success = c.end_time - now + timedelta(seconds=5)
                TimingContest.objects.update_or_create(
                    contest=c,
                    defaults={'statistic': now + delay_on_success}
                )

        if random_order:
            contests = list(contests)
            shuffle(contests)

        countrier = Countrier()

        count = 0
        total = 0
        progress_bar = tqdm(contests)
        for contest in progress_bar:
            resource = contest.resource
            if not hasattr(resource, 'module'):
                self.logger.error('Not found module contest = %s' % c)
                continue
            progress_bar.set_description(f'contest = {contest.title}')
            progress_bar.refresh()
            plugin = self._get_plugin(resource.module)
            total += 1
            parsed = False
            try:
                r = {}

                if hasattr(contest, 'stage'):
                    contest.stage.update()
                    count += 1
                    parsed = True
                    continue

                statistic = plugin.Statistic(
                    name=contest.title,
                    url=contest.url,
                    key=contest.key,
                    standings_url=contest.standings_url,
                    start_time=contest.start_time,
                    end_time=contest.end_time,
                )
                standings = statistic.get_standings()

                with transaction.atomic():
                    if 'url' in standings and standings['url'] != contest.standings_url:
                        contest.standings_url = standings['url']

                    if 'options' in standings:
                        contest_options = contest.info.get('standings', {})
                        standings_options = dict(contest_options)
                        standings_options.update(standings.pop('options'))

                        if self._canonize(standings_options) != self._canonize(contest_options):
                            contest.info['standings'] = standings_options

                    problems_time_format = standings.pop('problems_time_format', '{M}:{s:02d}')

                    result = standings.get('result', {})
                    if not no_update_results and result:
                        fields_set = set()
                        fields = list()
                        calculate_time = False
                        d_problems = {}
                        teams_viewed = set()
                        has_hidden = False

                        ids = {s.pk for s in Statistics.objects.filter(contest=contest)}
                        for r in tqdm(list(result.values()), desc=f'update results {contest}'):
                            for k, v in r.items():
                                if isinstance(v, str) and chr(0x00) in v:
                                    r[k] = v.replace(chr(0x00), '')

                            member = r.pop('member')
                            account, _ = Account.objects.get_or_create(resource=resource, key=member)

                            updated = now + timedelta(days=1)
                            if updated < account.updated:
                                account.updated = updated
                                account.save()

                            if r.get('name'):
                                while True:
                                    name = unescape(r['name'])
                                    if name == r['name']:
                                        break
                                    r['name'] = name
                                no_update_name = r.pop('_no_update_name', False)
                                if not no_update_name and account.name != r['name'] and member.find(r['name']) == -1:
                                    account.name = r['name']
                                    account.save()

                            country = r.get('country', None)
                            if country:
                                country = countrier.get(country)
                                if country and country != account.country:
                                    account.country = country
                                    account.save()

                            info = r.pop('info', {})
                            if info:
                                account.info = {**account.info, **info}
                                account.save()

                            problems = r.get('problems', {})

                            if 'team_id' not in r or r['team_id'] not in teams_viewed:
                                if 'team_id' in r:
                                    teams_viewed.add(r['team_id'])
                                for k, v in problems.items():
                                    if 'result' not in v:
                                        continue

                                    p = d_problems
                                    if 'division' in r:
                                        p = p.setdefault(r['division'], {})
                                    p = p.setdefault(k, {})
                                    p['n_teams'] = p.get('n_teams', 0) + 1

                                    ac = str(v['result']).startswith('+')
                                    try:
                                        result = float(v['result'])
                                        ac = ac or result > 0 and not v.get('partial', False)
                                    except Exception:
                                        pass
                                    if ac:
                                        p['n_accepted'] = p.get('n_accepted', 0) + 1

                            calc_time = contest.calculate_time or contest.start_time <= now < contest.end_time

                            defaults = {
                                'place': r.pop('place', None),
                                'solving': r.pop('solving', 0),
                                'upsolving': r.pop('upsolving', 0),
                            }

                            if not calc_time:
                                defaults['addition'] = dict(r)

                            statistic, created = Statistics.objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )

                            if not created:
                                ids.remove(statistic.pk)

                                if calc_time:
                                    p_problems = statistic.addition.get('problems', {})

                                    ts = min(int((now - contest.start_time).total_seconds()), contest.duration_in_secs)
                                    values = {
                                        'D': ts // (24 * 60 * 60),
                                        'H': ts // (60 * 60),
                                        'h': ts // (60 * 60) % 24,
                                        'M': ts // 60,
                                        'm': ts // 60 % 60,
                                        'S': ts,
                                        's': ts % 60,
                                    }
                                    time = problems_time_format.format(**values)

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
                                    has_hidden = True

                            if calc_time:
                                statistic.addition = dict(r)
                                statistic.save()

                            for k in r:
                                if k not in fields_set:
                                    fields_set.add(k)
                                    fields.append(k)

                        if has_hidden:
                            contest.timing.statistic = timezone.now() + timedelta(minutes=30)
                            contest.timing.save()

                        if contest.start_time <= now:
                            if now < contest.end_time:
                                contest.info['last_parse_statistics'] = now.strftime('%Y-%m-%d %H:%M:%S.%f+%Z')
                            elif 'last_parse_statistics' in contest.info:
                                contest.info.pop('last_parse_statistics')

                        if fields_set and not isinstance(r, OrderedDict):
                            fields.sort()

                        if ids:
                            first = Statistics.objects.filter(pk__in=ids).first()
                            self.logger.info(f'First deleted: {first}, account = {first.account}')
                            delete_info = Statistics.objects.filter(pk__in=ids).delete()
                            self.logger.info(f'Delete info: {delete_info}')
                            progress_bar.set_postfix(deleted=str(delete_info))

                        if self._canonize(fields) != self._canonize(contest.info.get('fields')):
                            contest.info['fields'] = fields

                        if calculate_time and not contest.calculate_time:
                            contest.calculate_time = True

                        problems = standings.pop('problems', None)
                        if 'division' in problems:
                            for d, ps in problems['division'].items():
                                for p in ps:
                                    if 'short' in p:
                                        p.update(d_problems.get(d, {}).get(p['short'], {}))
                            if isinstance(problems['division'], OrderedDict):
                                problems['divisions_order'] = list(problems['division'].keys())
                        else:
                            for p in problems:
                                if 'short' in p:
                                    p.update(d_problems.get(p['short'], {}))

                        if problems and self._canonize(problems) != self._canonize(contest.info.get('problems')):
                            contest.info['problems'] = problems

                        contest.save()

                        progress_bar.set_postfix(fields=str(fields))

                    action = standings.get('action')
                    if action is not None:
                        args = []
                        if isinstance(action, tuple):
                            action, *args = action
                        self.logger.info(f'Action {action} with {args}, contest = {contest}, url = {contest.url}')
                        if action == 'delete':
                            if now < contest.end_time:
                                self.logger.info(f'Skip. Try after = {contest.end_time - now}')
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
                url = contest.standings_url or contest.url
                self.logger.error(f'contest = {contest}, url = {url}, error = {e}, row = {r}')
                if stop_on_error:
                    self.logger.error(format_exc())
                    break
            if not parsed:
                if now < c.end_time and c.duration_in_secs <= limit_duration_in_secs:
                    delay = timedelta(minutes=0)
                else:
                    delay = resource.module.delay_on_error
                contest.timing.statistic = timezone.now() + delay
                contest.timing.save()
            else:
                stages = Stage.objects.filter(
                    contest__start_time__lte=contest.start_time,
                    contest__end_time__gte=contest.end_time,
                    contest__resource=contest.resource,
                )
                for stage in stages:
                    if Contest.objects.filter(pk=contest.pk, **stage.filter_params).exists():
                        stage.update()
        progress_bar.close()
        self.logger.info(f'Parse statistic: {count} of {total}.')
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

        if args.event is not None:
            contests = contests.filter(title__iregex=args.event)
        if args.only_new:
            has_statistics = Statistics.objects.filter(contest_id=OuterRef('pk'))
            contests = contests.annotate(has_statistics=Exists(has_statistics)).filter(has_statistics=False)
        self.parse_statistic(
            contests=contests,
            previous_days=args.days,
            limit=args.limit,
            with_check=not args.no_check_timing,
            stop_on_error=args.stop_on_error,
            random_order=args.random_order,
            no_update_results=args.no_update_results,
            freshness_days=args.freshness_days,
        )
