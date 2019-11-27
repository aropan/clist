from collections import OrderedDict

from django.shortcuts import render
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404
from django.db.models import Q, Exists, OuterRef
from el_pagination.decorators import page_template


from clist.models import Contest
from ranking.models import Statistics
from clist.templatetags.extras import slug
from clist.views import get_timezone, get_timeformat
from true_coders.models import Party


@page_template('standings_list_paging.html')
def standings_list(request, template='standings_list.html', extra_context=None):
    contests = Contest.objects \
        .annotate(has_statistics=Exists(Statistics.objects.filter(contest=OuterRef('pk')))) \
        .filter(has_statistics=True) \
        .order_by('-end_time', 'pk')
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
    contest = get_object_or_404(Contest, pk=contest_id)
    if slug(contest.title) != title_slug:
        return HttpResponseNotFound(f'Not found {slug(contest.title)} slug')

    statistics = Statistics.objects.filter(contest=contest)

    order = ['place_as_int', '-solving']
    statistics = statistics \
        .select_related('account') \
        .prefetch_related('account__coders')

    params = {}
    problems = contest.info.get('problems', {})
    if 'division' in problems:
        division = request.GET.get(
            'division',
            sorted(contest.info['problems']['division'].keys())[0],
        )
        params['division'] = division
        statistics = statistics.filter(addition__division=division)
        problems = problems['division'][division]

    last = None
    merge_problems = False
    for p in problems:
        if last and 'name' in last and last.get('name') == p.get('name') and last.get('full_score'):
            merge_problems = True
            last['colspan'] = last.get('colspan', 1) + 1
            p['skip'] = True
        else:
            last = p

    search = request.GET.get('search')
    if search:
        if search.startswith('party:'):
            _, party_slug = search.split(':')
            party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
            statistics = statistics.filter(account__coders__party__pk=party.pk)
        else:
            statistics = statistics.filter(Q(account__key__iregex=search) | Q(addition__name__iregex=search))

    countries = request.GET.getlist('country')
    countries = [c for c in countries if c]
    if countries:
        statistics = statistics.filter(account__country__in=countries)
        params['countries'] = set(countries)

    contest_fields = contest.info.get('fields', [])

    if 'team_id' in contest_fields:
        order.append('addition__name')
        statistics = statistics.distinct(*[f.lstrip('-') for f in order])

    order.append('pk')
    statistics = statistics.order_by(*order)

    fields = OrderedDict()
    for k, v in (
        ('penalty', 'Penalty'),
        ('total_time', 'Time'),
    ):
        if k in contest_fields:
            fields[k] = v

    has_detail = False
    for k in contest_fields:
        if k not in fields and k not in ['problems', 'name', 'team_id', 'solved', 'hack', 'challenges']:
            has_detail = True
            if request.GET.get('detail'):
                field = ' '.join(k.split('_'))
                if not field[0].isupper():
                    field = field.title()
                fields[k] = field
            else:
                break

    per_page = 50

    context = {
        'contest': contest,
        'statistics': statistics,
        'problems': problems,
        'params': params,
        'fields': fields,
        'per_page': per_page,
        'with_row_num': bool(search or countries),
        'start_num': (int(request.GET.get('page', '1')) - 1) * per_page,
        'has_detail': has_detail,
        'merge_problems': merge_problems,
        'truncatechars_name_problem': 10 * (2 if merge_problems else 1),
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)
