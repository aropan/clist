#!/usr/bin/env python3


import operator
from copy import deepcopy
from functools import reduce
from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from sql_util.utils import Exists
from tqdm import tqdm

from clist.models import Contest, Problem, Resource
from clist.views import update_problems
from utils.attrdict import AttrDict
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Parsing problems infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('clist.parse.problem')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-q', '--query', default=None, nargs='+', help='problem key or name')
        parser.add_argument('-f', '--force', action='store_true', help='get problems with min modified time')
        parser.add_argument('-l', '--limit', default=None, type=int,
                            help='limit users for one resource (default is 1000)')
        parser.add_argument('-cid', '--contest-id', default=None, type=int, help='problems from contest')
        parser.add_argument('-d', '--delay', default='1 day', type=str, help='modified field delay')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.resources:
            filters = [Q(host__startswith=r) | Q(short_host=r) for r in args.resources]
            resources = Resource.objects.filter(reduce(operator.or_, filters))
        else:
            resources = Resource.available_for_update_objects.filter(has_problem_update=True)

        problems = Problem.objects.filter(resource__in=resources)
        problems = problems.select_related('resource')
        if args.query:
            filters = [Q(key__contains=q) | Q(name__contains=q) for q in args.query]
            problems = problems.filter(reduce(operator.or_, filters))
        if args.contest_id:
            problems = problems.filter(Q(contest_id=args.contest_id) | Q(contests__id=args.contest_id))
        if args.delay and not args.force:
            delay = timezone.now() - parse_duration(args.delay)
            problems = problems.filter(modified__lte=delay)
        if args.limit:
            problems = problems.order_by('-created')[:args.limit]

        problems_filter = Q(problem__id__in=problems.values_list('pk', flat=True))
        contests = Contest.objects.annotate(has_problems=Exists('problem_set', filter=problems_filter))
        contests = contests.filter(has_problems=True)
        contests = contests.select_related('resource')
        contests = contests.order_by('-end_time')

        modules_cache = dict()
        for contest in tqdm(contests, total=contests.count(), desc='Contests'):
            cache = dict()
            resource = contest.resource
            if resource not in modules_cache:
                modules_cache[resource] = resource.plugin.Statistic
            plugin_statistic = modules_cache[resource]

            problems = deepcopy(contest.info.get('problems'))
            updated = False
            for problem in contest.problems_list:
                info = plugin_statistic.get_problem_info(problem, contest=contest, cache=cache)
                if info is None:
                    continue
                problem.update(info)
                updated = True
            if not updated:
                continue
            problems, contest.info['problems'] = contest.info['problems'], problems
            update_problems(contest, problems)
