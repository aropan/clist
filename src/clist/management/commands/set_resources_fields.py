#!/usr/bin/env python
# -*- coding: utf-8 -*-

from collections import defaultdict
from logging import getLogger
from math import isclose

from django.core.management.base import BaseCommand
from flatten_dict import flatten
from flatten_dict.reducers import make_reducer
from stringcolor import cs
from tqdm import tqdm

from clist.models import Contest, Problem, Resource
from ranking.models import Account, Statistics
from utils.attrdict import AttrDict


def set_accounts_fields(resources, logger):
    total = Account.objects.filter(resource__in=resources).count()
    with tqdm(total=total, desc='accounts') as pbar:
        for resource in resources.iterator():
            fields_types = defaultdict(set)
            pbar.set_postfix(resource=resource)

            for info in resource.account_set.values('info', 'rating_prediction').iterator():
                rating_prediction = info.pop('rating_prediction')
                info = info['info']
                info = flatten(info, reducer=make_reducer(delimiter='__'))
                if rating_prediction:
                    rating_prediction = flatten(rating_prediction, reducer=make_reducer(delimiter='__'))
                    raring_prediction = {f'rating_prediction__{k}': v for k, v in rating_prediction.items()}
                    info.update(raring_prediction)
                for k, v in info.items():
                    if Account.is_special_info_field(k):
                        continue
                    fields_types[k].add(type(v).__name__)
                pbar.update()
            fields_types = {k: list(v) for k, v in fields_types.items()}
            resource_accounts_fields_types = resource.accounts_fields_types

            fields = list(sorted(set(resource_accounts_fields_types.keys()) | set(fields_types.keys())))
            first_log = True
            for field in fields:
                new_types = list(sorted(fields_types.get(field, [])))
                orig_types = list(sorted(resource_accounts_fields_types.get(field, [])))
                if new_types == orig_types:
                    continue
                if (orig_types or new_types) and first_log:
                    logger.info(f'{resource} accounts fields:')
                    first_log = False
                if orig_types:
                    logger.info(cs(f'- {field}: {orig_types}', 'red'))
                if new_types:
                    logger.info(cs(f'+ {field}: {new_types}', 'green'))

            resource.accounts_fields['types'] = fields_types
            resource.save(update_fields=['accounts_fields'])


def set_problems_fields(resources, logger):
    total = Problem.objects.filter(resource__in=resources).count()
    with tqdm(total=total, desc='problems') as pbar:
        for resource in resources.iterator():
            fields_types = defaultdict(set)
            pbar.set_postfix(resource=resource)

            for info in resource.problem_set.values('info').iterator():
                info = info['info']
                info = flatten(info, reducer=make_reducer(delimiter='__'))
                for k, v in info.items():
                    if Problem.is_special_info_field(k):
                        continue
                    fields_types[k].add(type(v).__name__)
                pbar.update()
            fields_types = {k: list(v) for k, v in fields_types.items()}
            resource_problems_fields_types = resource.problems_fields.get('types', {})

            fields = list(sorted(set(resource_problems_fields_types.keys()) | set(fields_types.keys())))
            first_log = True
            for field in fields:
                new_types = list(sorted(fields_types.get(field, [])))
                orig_types = list(sorted(resource_problems_fields_types.get(field, [])))
                if new_types == orig_types:
                    continue
                if (orig_types or new_types) and first_log:
                    logger.info(f'{resource} problems fields:')
                    first_log = False
                if orig_types:
                    logger.info(cs(f'- {field}: {orig_types}', 'red'))
                if new_types:
                    logger.info(cs(f'+ {field}: {new_types}', 'green'))

            resource.problems_fields['types'] = fields_types
            resource.save(update_fields=['problems_fields'])


def set_statistics_fields(resources, logger):
    qs = Contest.objects
    total = qs.filter(resource__in=resources).count()
    with tqdm(total=total, desc='contests') as pbar:
        for resource in resources.iterator():
            fields_types = defaultdict(set)
            pbar.set_postfix(resource=resource)

            resource_qs = qs.filter(resource=resource).values('info__fields_types', 'rating_prediction_fields__types')
            for info in resource_qs.iterator():
                for prefix, fields_key in (
                    ('', 'info__fields_types'),
                    ('rating_prediction_', 'rating_prediction_fields__types'),
                ):
                    fields = info[fields_key] or {}
                    for k, v in fields.items():
                        if prefix:
                            k = f'{prefix}{k}'
                        if Statistics.is_special_addition_field(k):
                            continue
                        fields_types[k] |= set(v)
                pbar.update()

            fields_types = {k: list(v) for k, v in fields_types.items()}
            resource_statistics_fields_types = resource.statistics_fields.get('types', {})

            fields = list(sorted(set(resource_statistics_fields_types.keys()) | set(fields_types.keys())))
            first_log = True
            for field in fields:
                new_types = list(sorted(fields_types.get(field, [])))
                orig_types = list(sorted(resource_statistics_fields_types.get(field, [])))
                if new_types == orig_types:
                    continue
                if (orig_types or new_types) and first_log:
                    logger.info(f'{resource} statistics fields:')
                    first_log = False
                if orig_types:
                    logger.info(cs(f'- {field}: {orig_types}', 'red'))
                if new_types:
                    logger.info(cs(f'+ {field}: {new_types}', 'green'))

            resource.statistics_fields['types'] = fields_types
            resource.save(update_fields=['statistics_fields'])


def set_n_fields(resources, logger):
    for resource in resources:
        n_accounts = resource.account_set.count()
        n_contests = resource.contest_set.count()
        update_fields = []
        for field, new_value in (
            ('n_accounts', n_accounts),
            ('n_contests', n_contests),
        ):
            value = getattr(resource, field)
            if value != new_value:
                logger.info(f'{resource} {field}: {value} -> {new_value}')
                setattr(resource, field, new_value)
                update_fields.append(field)
        if update_fields:
            resource.save(update_fields=update_fields)


def set_avg_rating(resources, logger, default_min_n_participations=3):
    for resource in tqdm(resources.iterator(), total=resources.count()):
        ratings = []
        qs = resource.account_set.filter(rating__isnull=False)
        min_n_participations = resource.info.get('default_variables', {}).get('min_n_participations')
        min_n_participations = min_n_participations or default_min_n_participations
        qs = qs.filter(n_contests__gte=min_n_participations)
        qs = qs.values('rating')
        for rating in tqdm(qs.iterator(), total=qs.count()):
            ratings.append(rating['rating'])
        if ratings:
            avg_rating = sum(ratings) / len(ratings)
            logger.info(f'{resource} avg_rating by {len(ratings)} accounts: {avg_rating:.3f} <- {resource.avg_rating}')
            if resource.avg_rating and not isclose(resource.avg_rating, avg_rating):
                logger.info(f'{resource} avg_rating_diff: {resource.avg_rating - avg_rating}')
            resource.avg_rating = avg_rating
            resource.save(update_fields=['avg_rating'])


class Command(BaseCommand):
    help = 'Set resources fields'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.set_resources_fields')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('--avg-rating', action='store_true', help='update average rating')
        parser.add_argument('--problems-only', action='store_true', help='update problems only')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.get(args.resources) if args.resources else Resource.objects.all()
        self.logger.info(f'resources [{len(resources)}] = {[r.host for r in resources]}')

        if args.avg_rating:
            set_avg_rating(resources, logger=self.logger)
        elif args.problems_only:
            set_problems_fields(resources, logger=self.logger)
        else:
            set_accounts_fields(resources, logger=self.logger)
            set_problems_fields(resources, logger=self.logger)
            set_statistics_fields(resources, logger=self.logger)
            set_n_fields(resources, logger=self.logger)
