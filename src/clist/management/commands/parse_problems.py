#!/usr/bin/env python3


import operator
from functools import reduce
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from tqdm import tqdm

from clist.models import Problem, Resource
from utils.attrdict import AttrDict
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Parsing problems infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.problem')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-q', '--query', default=None, nargs='+', help='problem key or name')
        parser.add_argument('-f', '--force', action='store_true', help='get problems with min updated time')
        parser.add_argument('-l', '--limit', default=None, type=int,
                            help='limit users for one resource (default is 1000)')
        parser.add_argument('-cid', '--contest-id', default=None, type=int, help='problems from contest')
        parser.add_argument('-d', '--delay', default='1 day', type=str, help='updated field delay')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            filters = [Q(host__startswith=r) | Q(short_host=r) for r in args.resources]
            resources = Resource.objects.filter(reduce(operator.or_, filters))
        else:
            resources = Resource.available_for_update_objects.filter(has_problem_update=True)

        problems = Problem.objects.filter(resource__in=resources).order_by('updated')
        problems = problems.select_related('resource')
        if args.query:
            filters = [Q(key__contains=q) | Q(name__contains=q) for q in args.query]
            problems = problems.filter(reduce(operator.or_, filters))
        if args.contest_id:
            problems = problems.filter(Q(contest_id=args.contest_id) | Q(contests__id=args.contest_id))
        if args.delay and not args.force:
            delay = timezone.now() - parse_duration(args.delay)
            problems = problems.filter(updated__lte=delay)
        if args.limit:
            problems = problems.order_by('-created')[:args.limit]

        modules = dict()
        for problem in tqdm(problems, total=problems.count(), desc='Problems'):
            if problem.resource not in modules:
                modules[problem.resource] = problem.resource.plugin.Statistic
            module = modules[problem.resource]
            info = module.get_problem_info(problem)
            if info is None:
                continue
            problem.info.update(info)
            problem.save(update_fields=['info', 'updated'])
