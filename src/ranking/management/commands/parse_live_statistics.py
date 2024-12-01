#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import time

import humanize
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from ranking.models import ParseStatistics
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Parse live statistics'

    def add_arguments(self, parser):
        parser.add_argument('--dryrun', action='store_true', default=False)
        self.logger = logging.getLogger('ranking.parse.live_statistics')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        while True:
            now = timezone.now()
            parse_statistics = ParseStatistics.objects.filter(
                enable=True,
                contest__start_time__lte=now,
                contest__end_time__gte=now,
            )
            parse_statistics = parse_statistics.select_related('contest')

            for parse_stat in parse_statistics:
                now = timezone.now()
                if parse_stat.parse_time and parse_stat.parse_time > now:
                    self.logger.info(f'Skip {parse_stat.contest}, delay = {parse_stat.parse_time - now}')
                    continue
                self.logger.info(f'Parse statistic for {parse_stat.contest}')
                parse_stat.parse_time = now + parse_stat.delay
                parse_stat.save(update_fields=['parse_time'])
                if args.dryrun:
                    continue
                call_command(
                    'parse_statistic',
                    contest_id=parse_stat.contest.pk,
                    without_set_coder_problems=parse_stat.without_set_coder_problems,
                    without_stage=parse_stat.without_stage,
                    without_subscriptions=parse_stat.without_subscriptions,
                )

            parse_times = [p.parse_time for p in parse_statistics]
            if not parse_times:
                break

            parse_time = min(parse_times)
            delay = (parse_time - now).total_seconds()
            self.logger.info(f'Delay = {humanize.naturaldelta(delay)}, next parse time = {parse_time}')
            time.sleep(delay)
