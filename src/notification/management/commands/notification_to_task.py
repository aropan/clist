#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Case, DateTimeField, F, Q, When
from django.db.models.functions import Cast
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Contest
from notification.models import Notification, Task
from utils.timetools import Epoch
from utils.traceback_with_vars import colored_format_exc

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
            .filter(Q(notification_timing=None) | Q(modified__gt=F('notification_timing'))) \
            .order_by('start_time')

        now = timezone.now()
        if dryrun:
            logger.info(f'now = {now}')

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
            logger.info(f'updates = {updates}')

        notifies = notifies.select_related('coder')

        contests = Contest.visible.annotate(duration_time=Epoch(F('end_time') - F('start_time')))

        for notify in tqdm(notifies.iterator()):
            try:
                if ':' in notify.method:
                    category = notify.method.split(':', 1)[-1]
                else:
                    category = notify.method
                filt = notify.coder.get_contest_filter(category)

                before = timedelta(minutes=notify.before)

                qs = contests.filter(end_time__gte=now)

                if updates and notify.last_time and notify.with_updates:
                    qs_updates = updates.filter(filt, start_time__lt=min(now, notify.last_time) + before)
                    self.process(notify, qs_updates, 'UPD')
                    qs = qs.filter(~Q(pk__in=[c.pk for c in qs_updates]))

                qs = qs.filter(filt)

                if notify.with_virtual:
                    one_day = timedelta(days=1)
                    if_virtual = (~Q(duration_time=F('duration_in_secs'))
                                  & Q(duration_time__gt=one_day.total_seconds(), start_time__lt=now))
                    qs = qs.annotate(
                        time=Case(
                            When(start_time__gte=now, then=F('start_time')),
                            When(if_virtual, then=Cast(F('end_time') - one_day + before, output_field=DateTimeField())),
                            default=None,
                        )
                    )
                else:
                    qs = qs.filter(start_time__gte=now).annotate(time=F('start_time'))

                qs = qs.filter(time__isnull=False).order_by('time')

                if notify.last_time:
                    qs = qs.filter(time__gte=notify.last_time + before)
                else:
                    qs = qs.filter(time__gte=now + before)

                first = qs.first()
                if not first:
                    if dryrun:
                        logger.info(f'last_time = {notify.last_time} to none')
                    else:
                        notify.last_time = now + timedelta(hours=1)
                        notify.save()
                    continue

                delta = first.time - (now + before)
                if delta > timedelta(minutes=3):
                    new_time = first.time - before - timedelta(minutes=1)
                    if dryrun:
                        logger.info(f'last_time = {notify.last_time} to {new_time}')
                    else:
                        notify.last_time = new_time
                        notify.save()
                    continue

                if notify.period == Notification.EVENT:
                    last = first.time - now + timedelta(seconds=1)
                else:
                    last = before + notify.get_delta()
                qs = qs.filter(time__lt=now + last)

                new_time = now + last - before
                if dryrun:
                    logger.info(f'qs = {qs}')
                    logger.info(f'last_time = {notify.last_time} to {new_time}')
                else:
                    self.process(notify, qs)
                    notify.last_time = new_time
                    notify.save()
            except Exception as e:
                logger.debug(colored_format_exc())
                logger.warning(f'notification = {notify}')
                logger.error(f'Exception send notice: {e}')

        if not dryrun:
            with transaction.atomic():
                now = timezone.now()
                updates.update(notification_timing=now)
