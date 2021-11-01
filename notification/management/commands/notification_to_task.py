#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from datetime import timedelta
from traceback import format_exc

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Contest, TimingContest
from notification.models import Notification, Task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Add notice tasks'

    def process(self, notify, contests, prefix=''):
        if contests.exists():
            addition = {}
            addition['context'] = {'prefix': prefix}
            addition['contests'] = [contest.pk for contest in contests]

            Task.objects.create(
                notification=notify,
                addition=addition,
            )

    def add_arguments(self, parser):
        parser.add_argument('--coders', nargs='+')
        parser.add_argument('--dryrun', action='store_true', default=False)
        parser.add_argument('--methods', nargs='+')
        parser.add_argument('--reset', action='store_true', default=False)

    @print_sql_decorator()
    def handle(self, *args, **options):
        coders = options.get('coders')
        dryrun = options.get('dryrun')
        methods = options.get('methods')

        updates = Contest.visible\
            .filter(start_time__gte=timezone.now()) \
            .filter(Q(timing=None) | Q(modified__gt=F('timing__notification'))) \
            .order_by('start_time')

        now = timezone.now()
        if dryrun:
            logger.debug(f'now = {now}')

        notifies = Notification.objects.all()
        if coders is not None:
            notifies = notifies.filter(coder__user__username__in=coders)
        if methods:
            notifies = notifies.filter(method__in=methods)
        if dryrun and options.get('reset'):
            notifies.update(last_time=now)
        if not updates:
            notifies = notifies.filter(last_time__isnull=False, last_time__lte=now)
        elif dryrun:
            logger.debug(f'updates = {updates}')

        notifies = notifies.select_related('coder')
        for notify in tqdm(notifies.iterator()):
            try:
                if ':' in notify.method:
                    category = notify.method.split(':', 1)[-1]
                else:
                    category = notify.method
                filt = notify.coder.get_contest_filter(category)

                before = timedelta(minutes=notify.before)

                qs = Contest.visible.filter(start_time__gte=now)

                if updates and notify.last_time and notify.with_updates:
                    qs_updates = updates.filter(
                        filt,
                        start_time__gte=now + before,
                        start_time__lt=notify.last_time + before,
                    )
                    self.process(notify, qs_updates, 'UPD')
                    qs = qs.filter(~Q(pk__in=[c.pk for c in qs_updates]))

                if notify.last_time:
                    qs = qs.filter(start_time__gte=notify.last_time + before)
                qs = qs.filter(filt).order_by('start_time')

                first = qs.first()
                if not first:
                    if dryrun:
                        logger.debug(f'last_time = {notify.last_time} to none')
                    else:
                        notify.last_time = None
                        notify.save()
                    continue

                delta = first.start_time - (now + before)
                if delta > timedelta(minutes=3):
                    new_time = first.start_time - before - timedelta(minutes=1)
                    if dryrun:
                        logger.debug(f'last_time = {notify.last_time} to {new_time}')
                    else:
                        notify.last_time = new_time
                        notify.save()
                    continue

                if notify.period == Notification.EVENT:
                    last = first.start_time - now + timedelta(seconds=1)
                else:
                    last = before + notify.get_delta()
                qs = qs.filter(start_time__lt=now + last)

                new_time = now + last - before
                if dryrun:
                    logger.debug(f'qs = {qs}')
                    logger.debug(f'last_time = {notify.last_time} to {new_time}')
                else:
                    self.process(notify, qs)
                    notify.last_time = new_time
                    notify.save()
            except Exception:
                logger.error('Exception send notice:\n%s' % format_exc())

        if not dryrun:
            with transaction.atomic():
                now = timezone.now()
                for contest in updates:
                    TimingContest.objects.update_or_create(
                        contest=contest,
                        defaults={'notification': now}
                    )
