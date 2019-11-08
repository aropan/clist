#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import json
from random import shuffle
from tqdm import tqdm
from attrdict import AttrDict
# from traceback import format_exc
from datetime import timedelta
from logging import getLogger

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, F, Count

from ranking.models import Module, Statistics, Account
from clist.models import Contest, TimingContest


class Command(BaseCommand):
    help = 'Parsing statistics'
    SUCCESS_TIME_DELTA_ = timedelta(days=7)
    UNSUCCESS_TIME_DELTA_ = timedelta(days=1)

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.statistic')

    def add_arguments(self, parser):
        parser.add_argument('-d', '--days', type=int, help='how previous days for update')
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-e', '--event', help='regex event name')
        # parser.add_argument('-p', '--parties', metavar='PARTY', nargs='*', help='party name for update')
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
                        limit=None,
                        with_check=True,
                        stop_on_error=False,
                        random_order=False,
                        no_update_results=False):
        now = timezone.now()

        if with_check:
            contests = contests.filter(end_time__lt=timezone.now())

            if previous_days is not None:
                contests = contests.filter(
                    end_time__gt=timezone.now() - timedelta(days=previous_days)
                )
            else:
                contests = contests.filter(
                    end_time__gt=timezone.now() - F('resource__module__max_delay_after_end'),
                    end_time__lt=timezone.now() - F('resource__module__min_delay_after_end'),
                )
            contests = contests.filter(
                Q(timing__statistic__isnull=True) |
                Q(timing__statistic__lt=now)
            )

        if limit:
            contests = contests.filter(end_time__lt=timezone.now()).order_by('-start_time')[:limit]

        with transaction.atomic():
            for c in contests:
                module = c.resource.module
                delay = module.delay_on_success or module.max_delay_after_end
                TimingContest.objects.update_or_create(
                    contest=c,
                    defaults={'statistic': now + delay}
                )

        if random_order:
            contests = list(contests)
            shuffle(contests)

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
                statistic = plugin.Statistic(
                    name=contest.title,
                    url=contest.url,
                    key=contest.key,
                    standings_url=contest.standings_url,
                    start_time=contest.start_time,
                )
                standings = statistic.get_standings()

                with transaction.atomic():
                    if 'url' in standings and standings['url'] != contest.standings_url:
                        contest.standings_url = standings['url']
                        contest.save()

                    if standings.get('problems') \
                       and self._canonize(standings['problems']) != self._canonize(contest.info.get('problems')):
                        contest.info['problems'] = standings['problems']
                        contest.save()

                    if not no_update_results:
                        result = standings.get('result', {})
                        fields = set()

                        ids = {s.pk for s in Statistics.objects.filter(contest=contest)}
                        for r in tqdm(list(result.values()), desc='update results'):
                            member = r.pop('member')
                            account, _ = Account.objects.get_or_create(resource=resource, key=member)
                            if r.get('name') and account.name != r['name'] and member.find(r['name']) == -1:
                                account.name = r['name']
                                account.save()

                            defaults = {
                                'place': r.pop('place', None),
                                'solving': r.pop('solving', 0),
                                'upsolving': r.pop('upsolving', 0),
                                'addition': r,
                            }

                            statistic, created = Statistics.objects.update_or_create(
                                account=account,
                                contest=contest,
                                defaults=defaults,
                            )

                            if not created:
                                ids.remove(statistic.pk)

                            for k in r:
                                fields.add(k)

                        if ids:
                            delete_info = Statistics.objects.filter(pk__in=ids).delete()
                            progress_bar.set_postfix(deleted=str(delete_info))
                            self.logger.info(f'Delete info: {delete_info}')

                        fields = list(fields)
                        fields.sort()
                        if self._canonize(fields) != self._canonize(contest.info.get('fields')):
                            contest.info['fields'] = fields
                            contest.save()

                        progress_bar.set_postfix(fields=str(fields))

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
                self.logger.error(f'contest = {contest}, url = {contest.url}, error = {e}')
                # self.logger.error(format_exc())
                TimingContest.objects \
                    .filter(contest=contest) \
                    .update(statistic=timezone.now() + resource.module.delay_on_error)
                if stop_on_error:
                    break
        self.logger.info(f'Parse statistic: {count} of {total}')
        return count, total

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            if len(args.resources) == 1:
                modules = Module.objects.filter(resource__host__iregex=args.resources[0])
            else:
                modules = Module.objects.filter(resource__host__in=args.resources)
        else:
            modules = Module.objects.filter(min_delay_after_end__gt=timedelta())

        for module in modules:
            contests = Contest.objects.filter(resource=module.resource)
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
            )
