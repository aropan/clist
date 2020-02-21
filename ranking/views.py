import re
import copy
from collections import OrderedDict
from itertools import accumulate

from django.shortcuts import render
from django.utils import timezone
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect
from django.db.models import Q, Exists, OuterRef
from el_pagination.decorators import page_template


from clist.models import Contest
from ranking.models import Statistics, Module
from clist.templatetags.extras import slug
from clist.views import get_timezone, get_timeformat
from true_coders.models import Party
from clist.templatetags.extras import get_problem_key
from utils.regex import verify_regex


@page_template('standings_list_paging.html')
def standings_list(request, template='standings_list.html', extra_context=None):
    contests = Contest.objects \
        .annotate(has_statistics=Exists(Statistics.objects.filter(contest=OuterRef('pk')))) \
        .annotate(has_module=Exists(Module.objects.filter(resource=OuterRef('resource_id')))) \
        .filter(Q(has_statistics=True) | Q(end_time__lte=timezone.now())) \
        .order_by('-end_time', 'pk')

    if request.user.is_authenticated:
        all_standings = request.user.coder.settings.get('all_standings')
    else:
        all_standings = False

    switch = 'switch' in request.GET
    if bool(all_standings) == bool(switch):
        contests = contests.filter(has_statistics=True, has_module=True)
        if request.user.is_authenticated:
            contests = contests.filter(request.user.coder.get_contest_filter(['list']))

    search = request.GET.get('search')
    if search is not None:
        search_re = verify_regex(search)
        contests = contests.filter(Q(title__iregex=search_re) | Q(resource__host__iregex=search_re))

    context = {
        'contests': contests,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'all_standings': all_standings,
        'switch': switch,
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

    contest = get_object_or_404(Contest.objects.select_related('resource'), pk=contest_id)
    if slug(contest.title) != title_slug:
        return HttpResponseNotFound(f'Not found {slug(contest.title)} slug')

    contest_fields = contest.info.get('fields', [])

    statistics = Statistics.objects.filter(contest=contest)

    order = None
    resource_standings = contest.resource.info.get('standings', {})
    order = copy.copy(resource_standings.get('order'))
    if order:
        for f in order:
            if f.startswith('addition__') and f.split('__', 1)[1] not in contest_fields:
                order = None
                break
    if order is None:
        order = ['place_as_int', '-solving']

    options = contest.info.get('standings', {})

    # fixed fields
    fixed_fields = (('penalty', 'Penalty'), ('total_time', 'Time')) + tuple(options.get('fixed_fields', []))

    statistics = statistics \
        .select_related('account') \
        .prefetch_related('account__coders')

    has_country = 'country' in contest_fields or statistics.filter(account__country__isnull=False).exists()

    division = request.GET.get('division')
    if division == 'any':
        if 'place_as_int' in order:
            order.remove('place_as_int')
            order.append('place_as_int')
        fixed_fields += (('division', 'Division'),)

    if 'team_id' in contest_fields:
        order.append('addition__name')
        statistics = statistics.distinct(*[f.lstrip('-') for f in order])

    order.append('pk')
    statistics = statistics.order_by(*order)

    fields = OrderedDict()
    for k, v in fixed_fields:
        if k in contest_fields:
            fields[k] = v

    # field to select
    fields_to_select = {}
    for f in contest_fields:
        if f.lower() in ['institution', 'room', 'affiliation']:
            values = request.GET.getlist(f)
            if values:
                filt = Q()
                for q in values:
                    filt |= Q(**{f'addition__{f}': q})
                statistics = statistics.filter(filt)
            fields_to_select[f] = values

    for k in contest_fields:
        if (
            k not in fields
            and k not in ['problems', 'name', 'team_id', 'solved', 'hack', 'challenges', 'url', 'participant_type']
            and 'country' not in k
        ):
            if request.GET.get('detail'):
                field = ' '.join(k.split('_'))
                if not field[0].isupper():
                    field = field.title()
                fields[k] = field
            else:
                break

    per_page = options.get('per_page', 200)
    if per_page is None:
        per_page = 100500

    data_1st_u = options.get('1st_u')
    participants_info = {}
    if data_1st_u:
        seen = {}
        last_hl = None
        for s in statistics:
            match = re.search(data_1st_u['regex'], s.account.key)
            k = match.group('key')

            solving = s.solving
            penalty = s.addition.get('penalty')

            info = participants_info.setdefault(s.id, {})
            info['search'] = rf'^{k}'

            if k in seen or last_hl:
                p_info = participants_info.get(seen.get(k))
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
                if len(seen) == options.get('n_highlight'):
                    last_hl = info
    elif 'n_highlight' in options:
        for idx, s in enumerate(statistics[:options['n_highlight']], 1):
            participants_info[s.id] = {'n': idx}

    medals = options.get('medals')
    if medals:
        names = [m['name'] for m in medals]
        counts = [m['count'] for m in medals]
        medals = list(zip(names, accumulate(counts)))

    mod_penalty = {}
    first = statistics.first()
    if first and all('time' not in k for k in contest_fields):
        penalty = first.addition.get('penalty')
        if penalty and isinstance(penalty, int) and 'solved' not in first.addition:
            mod_penalty.update({'solving': first.solving, 'penalty': penalty})

    search = request.GET.get('search')
    if search:
        if search.startswith('party:'):
            _, party_slug = search.split(':')
            party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
            statistics = statistics.filter(Q(account__coders__in=party.coders.all()) |
                                           Q(account__coders__in=party.admins.all()) |
                                           Q(account__coders=party.author))
        else:
            search_re = verify_regex(search)
            statistics = statistics.filter(Q(account__key__iregex=search_re) | Q(addition__name__iregex=search_re))

    params = {}
    problems = contest.info.get('problems', {})
    if 'division' in problems:
        divisions_order = list(problems.get('divisions_order', sorted(contest.info['problems']['division'].keys())))
        divisions_order.append('any')
        if division not in divisions_order:
            division = divisions_order[0]
        params['division'] = division
        if division == 'any':
            _problems = OrderedDict()
            for div in reversed(divisions_order):
                for p in problems['division'].get(div, []):
                    k = get_problem_key(p)
                    if k not in _problems:
                        _problems[k] = p
            problems = list(_problems.values())
        else:
            statistics = statistics.filter(addition__division=division)
            problems = problems['division'][division]
    else:
        divisions_order = []

    for p in problems:
        if 'full_score' in p and abs(p['full_score'] - 1) > 1e-9:
            mod_penalty = {}
            break

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
    countries = set([c for c in countries if c])
    if countries:
        statistics = statistics.filter(account__country__in=countries)
        params['countries'] = countries

    page = request.GET.get('page', '1')
    start_num = (int(page) - 1 if page.isdigit() else 0) * per_page

    context = {
        'data_1st_u': data_1st_u,
        'participants_info': participants_info,
        'standings_options': options,
        'medals': medals,
        'mod_penalty': mod_penalty,
        'contest': contest,
        'statistics': statistics,
        'problems': problems,
        'params': params,
        'fields': fields,
        'divisions_order': divisions_order,
        'has_country': has_country,
        'per_page': per_page,
        'with_row_num': bool(search or countries),
        'start_num': start_num,
        'merge_problems': merge_problems,
        'fields_to_select': fields_to_select,
        'truncatechars_name_problem': 10 * (2 if merge_problems else 1),
        'with_detail': 'detail' in request.GET,
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)
