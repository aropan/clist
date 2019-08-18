from django.shortcuts import render
from django.http import HttpResponseNotFound
from django.db.models import Q, Exists, OuterRef
from el_pagination.decorators import page_template

from clist.models import Contest
from ranking.models import Statistics
from clist.templatetags.extras import slug
from clist.views import get_timezone, get_timeformat


@page_template('standings_list_paging.html')
def standings_list(request, template='standings_list.html', extra_context=None):
    contests = Contest.objects \
        .annotate(has_statistics=Exists(Statistics.objects.filter(contest=OuterRef('pk')))) \
        .filter(has_statistics=True) \
        .order_by('-end_time')
    search = request.GET.get('search')
    if search is not None:
        contests = contests.filter(Q(title__iregex=search) | Q(resource__host__iregex=search))

    context = {
        'contests': contests,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


@page_template('standings_paging.html')
def standings(request, title_slug, contest_id, template='standings.html', extra_context=None):
    contest = Contest.objects.get(pk=contest_id)
    if slug(contest.title) != title_slug:
        return HttpResponseNotFound(f'Not found {slug(contest.title)} slug')

    statistics = Statistics.objects.filter(contest=contest)

    statistics = statistics.extra(select={
        'place_as_int': "CAST(SPLIT_PART(place, '-', 1) AS INTEGER)"
    }).order_by('place_as_int', '-solving', '-upsolving')

    params = {}
    if 'division' in contest.info.get('problems'):
        division = sorted(contest.info['problems']['division'].keys())[0]
        params['division'] = division
        statistics = statistics.filter(addition__division=division)

    context = {
        'contest': contest,
        'statistics': statistics,
        'params': params,
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)
