#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import json
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
from django.db.models import Q, F, Count
from django_countries import countries

from ranking.models import Statistics, Account
from clist.models import Contest, Resource, TimingContest


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

    def parse_statistic(self,
                        contests,
                        previous_days=None,
                        freshness_days=None,
                        limit=None,
                        with_check=True,
                        stop_on_error=False,
                        random_order=False,
                        no_update_results=False):
        now = timezone.now()

        if with_check:
            if previous_days is not None:
                contests = contests.filter(end_time__gt=now - timedelta(days=previous_days), end_time__lt=now)
            else:
                contests = contests.distinct('id')
                contests = contests.filter(Q(timing__statistic__isnull=True) | Q(timing__statistic__lt=now))

                started = contests.filter(start_time__lt=now, end_time__gt=now, statistics__isnull=False)

                query = Q()
                query &= Q(end_time__gt=now - F('resource__module__max_delay_after_end'))
                query &= Q(end_time__lt=now - F('resource__module__min_delay_after_end'))
                ended = contests.filter(query)

                contests = started.union(ended)

        if freshness_days is not None:
            contests = contests.filter(modified__lt=now - timedelta(days=freshness_days))

        if limit:
            contests = contests.order_by('-start_time')[:limit]

        with transaction.atomic():
            for c in contests:
                module = c.resource.module
                delay = module.delay_on_success or module.max_delay_after_end
                if now < c.end_time and c.end_time < now + delay:
                    delay = c.end_time - now + timedelta(seconds=1)
                TimingContest.objects.update_or_create(
                    contest=c,
                    defaults={'statistic': now + delay}
                )

        if random_order:
            contests = list(contests)
            shuffle(contests)

        countries_name = {name.lower(): code for code, name in countries}
        countries_name.update({countries.alpha3(code): code for code, name in countries})
        missed_countries = set()

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
            try:
                r = {}

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
                        contest.save()

                    problems = standings.pop('problems', None)
                    if problems and self._canonize(problems) != self._canonize(contest.info.get('problems')):
                        contest.info['problems'] = problems
                        contest.save()

                    if not no_update_results:
                        result = standings.get('result', {})
                        fields_set = set()
                        fields = list()

                        calculate_time = False
                        ids = {s.pk for s in Statistics.objects.filter(contest=contest)}
                        for r in tqdm(list(result.values()), desc='update results'):
                            member = r.pop('member')
                            account, _ = Account.objects.get_or_create(resource=resource, key=member)

                            name = r.get('name')
                            no_update_name = r.pop('_no_update_name', False)
                            if not no_update_name and name and account.name != name and member.find(name) == -1:
                                account.name = name
                                account.save()

                            country = r.get('country', None)
                            if country and len(country) > 2:
                                c = countries_name.get(country.lower())
                                if not c:
                                    missed_countries.add(country)
                                country = c
                            if country and country != account.country:
                                account.country = country
                                account.save()

                            problems = r.get('problems', {})
                            calc_time = (
                                (contest.calculate_time or contest.start_time <= now < contest.end_time)
                                and 'division' not in problems
                            )

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

                                    ts = int((now - contest.start_time).total_seconds())
                                    time = f'{ts // 60}:{ts % 60:02}'

                                    for k, v in problems.items():
                                        if '?' in v.get('result', ''):
                                            calculate_time = True
                                        p = p_problems.get(k, {})
                                        if 'time' in v:
                                            continue
                                        has_change = v.get('result') != p.get('result')
                                        if not has_change or contest.end_time < now:
                                            if 'time' not in p:
                                                continue
                                            v['time'] = p['time']
                                        else:
                                            v['time'] = time

                            if calc_time:
                                statistic.addition = dict(r)
                                statistic.save()

                            for k in r:
                                if k not in fields_set:
                                    fields_set.add(k)
                                    fields.append(k)
                        if fields_set and not isinstance(r, OrderedDict):
                            fields.sort()

                        if ids:
                            delete_info = Statistics.objects.filter(pk__in=ids).delete()
                            progress_bar.set_postfix(deleted=str(delete_info))
                            self.logger.info(f'Delete info: {delete_info}')

                        if self._canonize(fields) != self._canonize(contest.info.get('fields')):
                            contest.info['fields'] = fields
                            contest.save()

                        progress_bar.set_postfix(fields=str(fields))

                    if calculate_time and not contest.calculate_time:
                        contest.calculate_time = True
                        contest.save()

                    action = standings.get('action')
                    if action is not None:
                        args = []
                        if isinstance(action, tuple):
                            action, *args = action
                        self.logger.info(f'Action {action} with {args}')
                        if action == 'delete':
                            contest.delete()
                        elif action == 'url':
                            contest.url = args[0]
                            contest.save()
                if 'result' in standings:
                    count += 1
            except Exception as e:
                url = contest.standings_url or contest.url
                self.logger.error(f'contest = {contest}, url = {url}, error = {e}, row = {r}')
                TimingContest.objects \
                    .filter(contest=contest) \
                    .update(statistic=timezone.now() + resource.module.delay_on_error)
                if stop_on_error:
                    self.logger.error(format_exc())
                    break
        if missed_countries:
            self.logger.warning(f'Missed countries = {missed_countries}')
        self.logger.info(f'Parse statistic: {count} of {total}')
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
            contests = Contest.objects.filter(resource__module__min_delay_after_end__gt=timedelta())

        if args.event is not None:
            contests = contests.filter(title__iregex=args.event)
        if args.only_new:
            contests = contests.annotate(n_stats=Count('statistics')).filter(n_stats=0)
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
