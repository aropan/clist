import re
from collections import OrderedDict
from itertools import accumulate

from django.shortcuts import render
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect
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
    search = request.GET.get('search')
    if search == '':
        url = request.get_full_path()
        url = re.sub('search=&?', '', url)
        url = re.sub(r'\?$', '', url)
        return redirect(url)

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

    has_detail = True
    for k in contest_fields:
        if k not in fields and k not in ['problems', 'name', 'team_id', 'solved', 'hack', 'challenges']:
            if request.GET.get('detail'):
                field = ' '.join(k.split('_'))
                if not field[0].isupper():
                    field = field.title()
                fields[k] = field
            else:
                break

    options = contest.info.get('standings', {})
    per_page = options.get('per_page', 50)

    data_1st_u = options.get('1st_u')
    if data_1st_u:
        infos = data_1st_u.setdefault('infos', {})
        seen = {}
        last_hl = None
        for s in statistics:
            match = re.search(data_1st_u['regex'], s.account.key)
            k = match.group('key')

            solving = s.solving
            penalty = s.addition.get('penalty')

            info = infos.setdefault(s.id, {})
            info['search'] = rf'^{k}'

            if k in seen or last_hl:
                p_info = infos.get(seen.get(k))
                if (
                    not p_info or
                    last_hl and (-last_hl['solving'], last_hl['penalty']) < (-p_info['solving'], p_info['penalty'])
                ):
                    p_info = last_hl

                info.update({
                    't_solving': p_info['solving'] - solving,
                    't_penalty': p_info['penalty'] - penalty if penalty is not None else None,
                })

            if k not in seen:
                seen[k] = s.id
                info.update({'n': len(seen), 'solving': solving, 'penalty': penalty})
                if len(seen) == data_1st_u.get('n_highlight'):
                    last_hl = info

    medals = options.get('medals')
    if medals:
        names = [m['name'] for m in medals]
        counts = [m['count'] for m in medals]
        medals = list(zip(names, accumulate(counts)))

    mod_penalty = {}
    first = statistics.first()
    if first:
        penalty = first.addition.get('penalty')
        if penalty and isinstance(penalty, int):
            mod_penalty.update({'solving': first.solving, 'penalty': penalty})

    search = request.GET.get('search')
    if search:
        if search.startswith('party:'):
            _, party_slug = search.split(':')
            party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
            statistics = statistics.filter(account__coders__party__pk=party.pk)
        else:
            statistics = statistics.filter(Q(account__key__iregex=search) | Q(addition__name__iregex=search))

    context = {
        'data_1st_u': data_1st_u,
        'medals': medals,
        'mod_penalty': mod_penalty,
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
        'with_detail': 'detail' in request.GET,
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)
