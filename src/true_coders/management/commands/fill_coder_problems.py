#!/usr/bin/env python3

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Prefetch, Q
from sql_util.utils import Exists
from tqdm import tqdm

from clist.models import Contest, ProblemVerdict, Resource
from clist.templatetags.extras import get_problem_solution, is_hidden, is_partial, is_reject, is_solved
from ranking.models import Statistics
from true_coders.models import Coder, CoderProblem
from utils.attrdict import AttrDict
from utils.logger import suppress_db_logging_context


class Command(BaseCommand):
    help = 'Fill coder problems using linked accounts'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('coders.fill_coder_problems')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-c', '--coders', metavar='CODER', nargs='*', help='coder usernames')
        parser.add_argument('-cid', '--contest', metavar='CONTEST', help='contest id')
        parser.add_argument('-nv', '--no-virtual', action='store_true', help='exclude virtual coders')
        parser.add_argument('-nf', '--no-filled', action='store_true', help='exclude filled coders')
        parser.add_argument('-n', '--limit', type=int, help='number of coders')

    def log_queryset(self, name, qs, limit=20):
        total = qs.count()
        self.logger.info(f'{name} ({total}) = {qs}')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        coders = Coder.objects.all()
        update_need_fill_coder_problems = False
        if args.no_filled:
            coders = coders.filter(Q(settings__need_fill_coder_problems=True))
            update_need_fill_coder_problems = True

        if args.coders:
            coders_filters = Q()
            for c in args.coders:
                coders_filters |= Q(username=c)
            coders = coders.filter(coders_filters)
            self.log_queryset('coders', coders)
            update_need_fill_coder_problems = False

        resources = Resource.objects.all()
        if args.resources:
            resource_filter = Q()
            for r in args.resources:
                resource_filter |= Q(host=r) | Q(short_host=r)
            resources = resources.filter(resource_filter)
            self.log_queryset('resources', resources)

            if not args.coders:
                coders = coders.annotate(has_resource=Exists('account', filter=Q(account__resource__in=resources)))
                coders = coders.filter(has_resource=True)
            update_need_fill_coder_problems = False

        if args.contest:
            contest = Contest.objects.get(pk=args.contest)
            problems = contest.problem_set.all()
            coders = coders.annotate(has_account=Exists('account', filter=Q(account__statistics__contest=contest)))
            coders = coders.filter(has_account=True)
            self.log_queryset('contest problems', problems)
            self.log_queryset('contest coders', coders)
            update_need_fill_coder_problems = False
        else:
            problems = None

        if args.no_virtual:
            coders = coders.exclude(is_virtual=True)

        if args.limit:
            coders = coders[:args.limit]

        n_created = 0
        n_total = 0
        n_deleted = 0
        for coder in tqdm(coders, total=coders.count(), desc='coders'):
            with suppress_db_logging_context(), transaction.atomic():
                def process_problem(problems, desc):
                    nonlocal n_created, n_total, n_deleted

                    old_problem_ids = coder.verdicts.filter(problem__in=problems).values_list('id', flat=True)
                    old_problem_ids = set(old_problem_ids)

                    problems = problems.select_related('resource')
                    problems = problems.prefetch_related('contests')

                    statistics = Statistics.objects.filter(account__coders=coder)
                    problems = problems.prefetch_related(Prefetch('contests__statistics_set', queryset=statistics))
                    problems = problems.filter(contests__statistics__account__coders=coder)

                    if args.contest:
                        problem_iter = problems
                    else:
                        problem_iter = tqdm(problems, total=len(problems), desc=desc)

                    for problem in problem_iter:
                        solution = get_problem_solution(problem)
                        if 'result' not in solution:
                            continue
                        result = solution['result']
                        if is_solved(result, with_upsolving=True):
                            verdict = ProblemVerdict.SOLVED
                        elif is_reject(result, with_upsolving=True):
                            verdict = ProblemVerdict.REJECT
                        elif is_hidden(result, with_upsolving=True):
                            verdict = ProblemVerdict.HIDDEN
                        elif is_partial(result, with_upsolving=True):
                            verdict = ProblemVerdict.PARTIAL
                        else:
                            continue
                        status, created = CoderProblem.objects.update_or_create(
                            coder=coder,
                            problem=problem,
                            defaults={'verdict': verdict},
                        )
                        n_created += created
                        n_total += 1
                        old_problem_ids.discard(status.id)
                    n_deleted += len(old_problem_ids)
                    coder.verdicts.filter(id__in=old_problem_ids).delete()

                if problems is not None:
                    process_problem(problems, desc='problems')
                else:
                    coder_resources = resources.annotate(has_coder=Exists('account', filter=Q(coders=coder)))
                    coder_resources = coder_resources.filter(has_coder=True)
                    for resource in tqdm(coder_resources, total=len(coder_resources), desc='resources'):
                        resource_problems = resource.problem_set.all()
                        process_problem(resource_problems, desc=f'{resource}')
            if update_need_fill_coder_problems:
                coder.settings.pop('need_fill_coder_problems', None)
                coder.save(update_fields=['settings'])

        self.logger.info(f'n_created = {n_created}, n_deleted = {n_deleted}, n_total = {n_total}')
