#!/usr/bin/env python3

import logging
import re
from datetime import timedelta

import coloredlogs
import dateutil
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Min

from clist.models import Contest
from clist.templatetags.extras import slug
from utils.attrdict import AttrDict

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


class Command(BaseCommand):
    help = 'Inherit stage'

    def add_arguments(self, parser):
        parser.add_argument('--regex', type=str, help='Original stage title regex', required=True)
        parser.add_argument('--title', type=str, help='Title of new stage', required=True)
        parser.add_argument('--url', type=str, help='Url of new stage')
        parser.add_argument('--start-time', type=str, help='Start time of new stage')
        parser.add_argument('--end-time', type=str, help='End time of new stage')
        parser.add_argument('--time-regex', type=str, help='Regex contest title to find range time')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        with transaction.atomic():
            original_contest = Contest.objects.get(stage__isnull=False, title__iregex=args.regex)
            logger.info(f'original contest = {original_contest}')

            time_qs = original_contest.resource.contest_set.filter(title__regex=args.time_regex or args.title)
            time_qs = time_qs.filter(stage__isnull=True)

            if args.start_time:
                start_time = dateutil.parser.parse(args.start_time)
            else:
                start_time = time_qs.aggregate(Min('start_time'))['start_time__min'] - timedelta(days=1)

            if args.end_time:
                end_time = dateutil.parser.parse(args.end_time)
            else:
                end_time = time_qs.aggregate(Max('end_time'))['end_time__max'] + timedelta(days=1)

            contest, created = Contest.objects.update_or_create(
                title=args.title,
                host=original_contest.host,
                resource=original_contest.resource,
                key=slug(args.title),
                defaults=dict(
                    start_time=start_time,
                    end_time=end_time,
                    url=args.url if args.url else original_contest.url,
                ),
            )

            if created:
                logger.info(f'new contest = {contest}')

            if getattr(contest, 'stage', None):
                stage = contest.stage
                stage.filter_params = original_contest.stage.filter_params
                stage.score_params = original_contest.stage.score_params
                stage.save()
            else:
                stage = original_contest.stage
                stage.pk = None
                stage.contest = contest
                stage.save()
                logger.info(f'new stage = {stage}')

            exclude_stages = stage.score_params.get('advances', {}).get('exclude_stages')
            if exclude_stages is not None:
                exclude_stages.clear()

                new_title = re.sub(r'(.*\s*)([0-9]+)', lambda m: f'{m.group(1)}{int(m.group(2)) - 1}', args.title)
                if new_title != args.title:
                    exclude_contest = Contest.objects.filter(stage__isnull=False, title=new_title).first()
                    if exclude_contest:
                        exclude_stage = exclude_contest.stage
                        exclude_stages.extend(exclude_stage.score_params.get('advances', {}).get('exclude_stages', []))
                        exclude_stages.append(exclude_stage.pk)

                logger.info(f'exclude stages = {exclude_stages}')
                stage.save()
