from django.db.models import Q
from django.shortcuts import redirect
from el_pagination.decorators import page_templates

from submissions.models import Submission

from clist.templatetags.extras import get_problem_name, get_problem_short
from pyclist.decorators import context_pagination, inject_contest
from ranking.models import Account


@page_templates((
    ('submissions_paging.html', 'submissions_paging'),
    ('standings_groupby_paging.html', 'groupby_paging'),
))
@context_pagination()
@inject_contest()
def submissions(request, contest, template='submissions.html'):
    fields_to_select = {}
    submissions = Submission.objects.all().order_by('-contest_time')

    submissions = submissions.filter(contest=contest)
    submissions_filter = Q()

    statistics = [s for s in request.GET.getlist('statistic') if s]
    if statistics:
        accounts = list(Account.objects.filter(statistics__pk__in=statistics).values_list('pk', flat=True))
        request.GET = request.GET.copy()
        del request.GET['statistic']
        for a in accounts:
            request.GET.appendlist('account', a)
        return redirect(request.path + '?' + request.GET.urlencode())

    problems = list(contest.problems_list)
    if problems:
        problems_options = {}
        for p in problems:
            problem_short = get_problem_short(p)
            problem_name = get_problem_name(p)
            problem_text = problem_short if problem_name == problem_short else f'{problem_short}. {problem_name}'
            problems_options[problem_short] = problem_text

        fields_to_select['problem'] = {'field': 'problem', 'options': problems_options, 'icon': 'problems'}
        problems = [p for p in request.GET.getlist('problem') if p]
        if problems:
            submissions_filter &= Q(problem_short__in=problems)

    verdicts = list(submissions.order_by('verdict').distinct('verdict').values_list('verdict', flat=True))
    if verdicts:
        fields_to_select['verdict'] = {'field': 'verdict', 'options': verdicts, 'icon': 'verdicts'}
        verdicts = [p for p in request.GET.getlist('verdict') if p]
        if verdicts:
            submissions_filter &= Q(verdict_id__in=verdicts)

    languages = list(submissions.order_by('language').distinct('language').values_list('language', flat=True))
    if languages:
        fields_to_select['language'] = {'field': 'language', 'options': languages, 'icon': 'languages'}
        languages = [p for p in request.GET.getlist('language') if p]
        if languages:
            submissions_filter &= Q(language_id__in=languages)

    accounts = [a for a in request.GET.getlist('account') if a]
    if accounts:
        submissions_filter &= Q(account__in=accounts)
        accounts = Account.objects.filter(pk__in=accounts)

    timeline = request.GET.get('timeline')
    if timeline:
        submissions_filter &= Q(contest_time__lte=float(timeline) * contest.duration)

    submissions = submissions.filter(submissions_filter)
    submissions = submissions.prefetch_related('tests__verdict')
    submissions = submissions.select_related('contest__resource', 'account__resource', 'statistic')

    context = {
        'contest': contest,
        'accounts': accounts,
        'fields_to_select': fields_to_select,
        'submissions': submissions,
        'per_page': 50,
        'per_page_more': 200,
    }
    return template, context
