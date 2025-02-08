#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clist.models import Contest, Promotion, Resource
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Detect major contests'

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self.logger = logging.getLogger('ranking.detect.major_contests')

    def add_arguments(self, parser):
        parser.add_argument('-n', '--dryrun', action='store_true', default=False)
        parser.add_argument('-r', '--resources', nargs='*', default=[])

    @transaction.atomic()
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        contests = Contest.objects
        if args.resources:
            resources = Resource.get(args.resources)
            contests = contests.filter(resource__in=resources)

        now = timezone.now()
        contests = contests.filter(end_time__lt=now, live_statistics__isnull=False)
        contests = contests.order_by('-end_time')

        for contest in contests:
            major_contests = contest.similar_contests()
            major_contests = major_contests.filter(
                start_time__gt=now,
                start_time__lt=now + timezone.timedelta(days=7),
            )
            for major_contest in major_contests.exclude(live_statistics__isnull=False):
                Promotion.create_major_contest(major_contest)
                contest.live_statistics.create_for_contest(major_contest)
