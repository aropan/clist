#!/usr/bin/env python3


from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from tqdm import tqdm

from clist.models import Problem, Resource
from clist.templatetags.extras import canonize
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from utils.attrdict import AttrDict
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Parsing problems infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.parse.archive_problems')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-f', '--force', action='store_true', help='force update problems')
        parser.add_argument('-l', '--limit', default=None, type=int, help='limit problems for one resource')
        parser.add_argument('-d', '--delay', default='1 day', type=str, help='modified field delay')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            resources = Resource.get(args.resources)
        else:
            resources = Resource.available_for_update_objects.filter(has_problem_archive=True)

        if args.delay and not args.force:
            delay = timezone.now() - parse_duration(args.delay)
            resource_filter = Q(problem_archive_update_time__lte=delay) | Q(problem_archive_update_time__isnull=True)
            resources = resources.filter(resource_filter)

        for resource in resources:
            event_log = EventLog.objects.create(name='parse_archive_problems',
                                                related=resource,
                                                status=EventStatus.IN_PROGRESS)
            with failed_on_exception(event_log):
                counter = defaultdict(int)
                now = timezone.now()
                archive_problems = resource.plugin.Statistic.get_archive_problems(resource=resource, limit=args.limit)
                problem_keys = [archive_problem['key'] for archive_problem in archive_problems]
                contest_problems = Problem.objects.filter(resource=resource, key__in=problem_keys)
                contest_problems = contest_problems.filter(Q(contest__isnull=False) | Q(contests__isnull=False))
                contest_problem_keys = set(contest_problems.values_list('key', flat=True))
                problem_time = now
                problem_ids = []
                for archive_problem in tqdm(archive_problems):
                    problem_key = archive_problem['key']
                    tags = archive_problem.get('info', {}).pop('tags', [])

                    if problem_key in contest_problem_keys:
                        updated_fields = []
                        problem = Problem.objects.get(resource=resource, key=problem_key)
                        info = deepcopy(problem.info)
                        archive_info = archive_problem.get('info', {})
                        info.update(archive_info)
                        if canonize(problem.info) != canonize(info):
                            problem.info = info
                            updated_fields.append('info')
                            counter['updated'] += 1
                        else:
                            counter['not_changed'] += 1
                        for field in 'n_accepted_submissions', 'n_total_submissions':
                            if field in archive_problem:
                                setattr(problem, field, archive_problem[field])
                                updated_fields.append(field)
                        if updated_fields:
                            problem.save(update_fields=updated_fields)
                        if problem.time is not None:
                            problem_time = problem.time - timedelta(milliseconds=1)
                    else:
                        if 'archive_url' not in archive_problem and resource.problem_url:
                            archive_problem['archive_url'] = resource.problem_url.format(**archive_problem)
                        archive_problem['is_archive'] = True
                        problem, created = Problem.objects.update_or_create(resource=resource,
                                                                            key=problem_key,
                                                                            defaults=archive_problem)
                        problem.update_tags(tags, replace=True)
                        updated_fields = []
                        if problem.time is None and problem_time:
                            problem.time = problem_time
                            updated_fields.append('time')

                        if updated_fields:
                            problem.save(update_fields=updated_fields)

                        if created:
                            counter['created'] += 1
                        counter['done'] += 1

                    problem_ids.append(problem.id)

                if resource.problem_rating_predictor and (predictor_model := resource.load_problem_rating_predictor()):
                    rating_changes = []
                    problems = resource.problem_set.filter(id__in=problem_ids)
                    problem_filter = resource.problem_rating_predictor['filter']
                    if problem_filter:
                        problems = problems.filter(**problem_filter)
                    df = resource.problem_rating_predictor_data(problems)
                    df = df.drop(['rating'], axis=1)
                    ratings = predictor_model.predict(df)
                    for problem, rating in zip(problems, ratings):
                        rating = round(rating)
                        if problem.rating is not None:
                            rating_changes.append(problem.rating - rating)
                        if problem.rating != rating:
                            problem.rating = rating
                            problem.save(update_fields=['rating'])
                            counter['rating'] += 1
                        else:
                            counter['rating_not_changed'] += 1
                    if rating_changes:
                        n_rating_changes = len(rating_changes)
                        self.logger.info(f'Rating change = {sum(rating_changes) / n_rating_changes}')
                        self.logger.info(f'Rating abs change = {sum(map(abs, rating_changes)) / n_rating_changes}')

                if not args.force:
                    resource.problem_archive_update_time = now
                    resource.save(update_fields=['problem_archive_update_time'])

                message = f'counter = {dict(counter)}'
                self.logger.info(f'{resource}: {message}')
                event_log.update_status(EventStatus.COMPLETED, message=message)
