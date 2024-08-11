#!/usr/bin/env python3


import operator
from functools import reduce
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from sklearn.model_selection import RandomizedSearchCV

from clist.models import Resource
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'Train problem rating predictor'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.train.problem_rating_predictor')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update', required=True)
        parser.add_argument('-n', '--n-iters', type=int, default=100, help='number of iterations for search cv')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.exclude(problem_rating_predictor__exact={})
        filters = [Q(host__startswith=r) | Q(short_host=r) for r in args.resources]
        resources = resources.filter(reduce(operator.or_, filters))

        for resource in resources:
            problems = resource.problem_set.filter(rating__isnull=False)
            problem_filter = resource.problem_rating_predictor['filter']
            if problem_filter:
                problems = problems.exclude(**problem_filter)

            df = resource.problem_rating_predictor_data(problems)
            X = df.drop(['rating'], axis=1)
            y = df['rating']

            predictor_model, param_distributions = resource.problem_rating_predictor_model()
            random_search = RandomizedSearchCV(estimator=predictor_model, param_distributions=param_distributions,
                                               n_iter=args.n_iters, scoring='neg_root_mean_squared_error', cv=5,
                                               verbose=1, n_jobs=-1, error_score='raise')
            random_search.fit(X, y)
            self.logger.info(f'Best params: {random_search.best_params_}')
            self.logger.info(f'Best RMSE: {-random_search.best_score_}')

            resource.save_problem_rating_predictor(random_search.best_estimator_)
