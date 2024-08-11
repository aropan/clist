#!/usr/bin/env python3


import operator
from collections import defaultdict
from datetime import timedelta
from functools import reduce
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from tqdm import tqdm

from clist.models import Problem, Resource
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Parsing problems infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.parse.new_problems')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-l', '--limit', default=None, type=int, help='limit problems for one resource')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            filters = [Q(host__startswith=r) | Q(short_host=r) for r in args.resources]
            resources = Resource.objects.filter(reduce(operator.or_, filters))
        else:
            resources = Resource.available_for_update_objects.filter(has_new_problems=True)

        counter = defaultdict(int)
        for resource in resources:
            new_problems = resource.plugin.Statistic.get_new_problems(resource=resource, limit=args.limit)
            problem_keys = [new_problem['key'] for new_problem in new_problems]
            contest_problems = Problem.objects.filter(resource=resource, key__in=problem_keys)
            contest_problems = contest_problems.filter(Q(contest__isnull=False) | Q(contests__isnull=False))
            contest_problem_keys = set(contest_problems.values_list('key', flat=True))
            problem_time = timezone.now()
            problem_ids = []
            for new_problem in tqdm(new_problems):
                problem_key = new_problem['key']
                tags = new_problem.get('info', {}).pop('tags', [])

                if problem_key in contest_problem_keys:
                    problem = Problem.objects.get(resource=resource, key=problem_key)
                    problem.info.update(new_problem.get('info', {}))
                    problem.info.pop('total_accepted', None)
                    problem.info.pop('total_submissions', None)
                    updated_fields = ['info']
                    for field in 'n_accepted_submissions', 'n_total_submissions':
                        if field in new_problem:
                            setattr(problem, field, new_problem[field])
                            updated_fields.append(field)
                    problem.save(update_fields=updated_fields)
                    if problem.time is not None:
                        problem_time = problem.time - timedelta(milliseconds=1)
                    counter['updated'] += 1
                else:
                    if 'archive_url' not in new_problem:
                        new_problem['archive_url'] = resource.problem_url.format(**new_problem)
                    new_problem['is_archive'] = True
                    problem, created = Problem.objects.update_or_create(resource=resource,
                                                                        key=problem_key,
                                                                        defaults=new_problem)
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

            if resource.problem_rating_predictor:
                predictor_model = resource.load_problem_rating_predictor()
                if predictor_model is not None:
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
                            counter['rating'] += 1
                            problem.rating = rating
                            problem.save(update_fields=['rating'])
                    if rating_changes:
                        n_rating_changes = len(rating_changes)
                        self.logger.info(f'Rating change = {sum(rating_changes) / n_rating_changes}')
                        self.logger.info(f'Rating abs change = {sum(map(abs, rating_changes)) / n_rating_changes}')

        self.logger.info(f'counter = {dict(counter)}')
