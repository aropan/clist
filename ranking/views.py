import re
import copy
from collections import OrderedDict

from django.conf import settings
from django.db import models, connection
from django.contrib.auth.decorators import login_required
from django.db.models import Case, When, F, Q, Exists, OuterRef, Count, Avg
from django.db.models.functions import Cast
from django.db.models.expressions import RawSQL
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from el_pagination.decorators import page_template, page_templates

from clist.models import Contest
from ranking.models import Statistics, Module
from clist.templatetags.extras import slug
from clist.views import get_timezone, get_timeformat
from true_coders.models import Party
from clist.templatetags.extras import get_problem_key, get_country_name
from utils.regex import get_iregex_filter, verify_regex
from utils.json_field import JSONF
from utils.list_as_queryset import ListAsQueryset


@page_template('standings_list_paging.html')
def standings_list(request, template='standings_list.html', extra_context=None):
    contests = Contest.objects \
        .select_related('timing') \
        .annotate(has_statistics=Exists(Statistics.objects.filter(contest=OuterRef('pk')))) \
        .annotate(has_module=Exists(Module.objects.filter(resource=OuterRef('resource_id')))) \
        .filter(Q(has_statistics=True) | Q(end_time__lte=timezone.now())) \
        .order_by('-end_time')

    has_perm_reset_statistic_timing = False
    all_standings = False
    if request.user.is_authenticated:
        all_standings = request.user.coder.settings.get('all_standings')
        has_perm_reset_statistic_timing = request.user.has_perm('reset_contest_statistic_timing')

    switch = 'switch' in request.GET
    if bool(all_standings) == bool(switch):
        contests = contests.filter(has_statistics=True, has_module=True)
        if request.user.is_authenticated:
            contests = contests.filter(request.user.coder.get_contest_filter(['list']))

    search = request.GET.get('search')
    if search is not None:
        contests = contests.filter(get_iregex_filter(search, 'title', 'resource__host'))

    context = {
        'contests': contests,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'all_standings': all_standings,
        'has_perm_reset_statistic_timing': has_perm_reset_statistic_timing,
        'switch': switch,
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


@page_templates((
    ('standings_paging.html', 'standings_paging'),
    ('standings_groupby_paging.html', 'groupby_paging'),
))
def standings(request, title_slug, contest_id, template='standings.html', extra_context=None):
    groupby = request.GET.get('groupby')
    if groupby == 'none':
        groupby = None

    search = request.GET.get('search')
    if search == '':
        url = request.get_full_path()
        url = re.sub('search=&?', '', url)
        url = re.sub(r'\?$', '', url)
        return redirect(url)
    orderby = request.GET.getlist('orderby')
    if orderby:
        if '--' in orderby:
            updated_orderby = []
        else:
            orderby_set = set()
            unique_orderby = reversed([
                f for k, f in [(f.lstrip('-'), f) for f in reversed(orderby)]
                if k not in orderby_set and not orderby_set.add(k)
            ])
            updated_orderby = [f for f in unique_orderby if not f.startswith('--')]

        if updated_orderby != orderby:
            query = request.GET.copy()
            query.setlist('orderby', updated_orderby)
            return redirect(f'{request.path}?{query.urlencode()}')

    contest = get_object_or_404(Contest.objects.select_related('resource'), pk=contest_id)
    if slug(contest.title) != title_slug:
        return HttpResponseNotFound()

    with_row_num = False

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
    fixed_fields = (
        ('penalty', 'Penalty'),
        ('total_time', 'Time'),
        ('advanced', 'Advance')
    ) + tuple(options.get('fixed_fields', []))

    statistics = statistics \
        .select_related('account') \
        .select_related('account__resource') \
        .prefetch_related('account__coders')

    has_country = (
        'country' in contest_fields or
        '_countries' in contest_fields or
        statistics.filter(account__country__isnull=False).exists()
    )

    division = request.GET.get('division')
    if division == 'any':
        with_row_num = True
        if 'place_as_int' in order:
            order.remove('place_as_int')
            order.append('place_as_int')
        fixed_fields += (('division', 'Division'),)

    if 'team_id' in contest_fields and not groupby:
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
        f = f.strip('_')
        if f.lower() in ['institution', 'room', 'affiliation', 'city', 'languages', 'school', 'class', 'job', 'region']:
            fields_to_select[f] = request.GET.getlist(f)

    with_detail = request.GET.get('detail', 'true') in ['true', 'on']
    if request.user.is_authenticated:
        coder = request.user.coder
        if 'detail' in request.GET:
            coder.settings['standings_with_detail'] = with_detail
            coder.save()
        else:
            with_detail = coder.settings.get('standings_with_detail', False)
    else:
        coder = None

    if with_detail:
        for k in contest_fields:
            if (
                k not in fields
                and k not in ['problems', 'name', 'team_id', 'solved', 'hack', 'challenges', 'url', 'participant_type',
                              'division']
                and not (k == 'medal' and '_medal_title_field' in contest_fields)
                and 'country' not in k
                and not k.startswith('_')
            ):
                fields[k] = k

    for k, field in fields.items():
        field = ' '.join(k.split('_'))
        if field and not field[0].isupper():
            field = field.title()
        fields[k] = field

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

    mod_penalty = {}
    first = statistics.first()
    if first and all('time' not in k for k in contest_fields):
        penalty = first.addition.get('penalty')
        if penalty and isinstance(penalty, int) and 'solved' not in first.addition:
            mod_penalty.update({'solving': first.solving, 'penalty': penalty})

    params = {}
    problems = contest.info.get('problems', {})
    if 'division' in problems:
        divisions_order = list(problems.get('divisions_order', sorted(contest.info['problems']['division'].keys())))
    elif 'divisions_order' in contest.info:
        divisions_order = contest.info['divisions_order']
    else:
        divisions_order = []

    if divisions_order:
        divisions_order.append('any')
        if division not in divisions_order:
            division = divisions_order[0]
        params['division'] = division
        if 'division' in problems:
            if division == 'any':
                _problems = OrderedDict()
                for div in reversed(divisions_order):
                    for p in problems['division'].get(div, []):
                        k = get_problem_key(p)
                        if k not in _problems:
                            _problems[k] = p
                        else:
                            for f in 'n_accepted', 'n_teams':
                                if f in p:
                                    _problems[k][f] = _problems[k].get(f, 0) + p[f]

                problems = list(_problems.values())
            else:
                problems = problems['division'][division]
        if division != 'any':
            statistics = statistics.filter(addition__division=division)

    for p in problems:
        if 'full_score' in p and isinstance(p['full_score'], (int, float)) and abs(p['full_score'] - 1) > 1e-9:
            mod_penalty = {}
            break

    last = None
    merge_problems = False
    for p in problems:
        if last and last.get('full_score') and (
            'name' in last and last.get('name') == p.get('name') or
            'group' in last and last.get('group') == p.get('group')
        ):
            merge_problems = True
            last['colspan'] = last.get('colspan', 1) + 1
            p['skip'] = True
        else:
            last = p

    # own_stat = statistics.filter(account__coders=coder).first() if coder else None

    # filter by search
    search = request.GET.get('search')
    if search:
        with_row_num = True
        if search.startswith('party:'):
            _, party_slug = search.split(':')
            party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
            statistics = statistics.filter(Q(account__coders__in=party.coders.all()) |
                                           Q(account__coders__in=party.admins.all()) |
                                           Q(account__coders=party.author))
        else:
            search_re = verify_regex(search)
            statistics = statistics.filter(Q(account__key__iregex=search_re) | Q(addition__name__iregex=search_re))

    # filter by country
    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        with_row_num = True
        cond = Q(account__country__in=countries)
        if 'None' in countries:
            cond |= Q(account__country__isnull=True)
        if '_countries' in contest_fields:
            for code in countries:
                name = get_country_name(code)
                if name:
                    cond |= Q(addition___countries__icontains=name)

        statistics = statistics.filter(cond)
        params['countries'] = countries

    # filter by field to select
    for field, values in fields_to_select.items():
        if not values:
            continue
        with_row_num = True
        filt = Q()
        if field == 'languages':
            for lang in values:
                filt |= Q(**{f'addition___languages__contains': [lang]})
        else:
            query_field = f'addition__{field}'
            statistics = statistics.annotate(**{f'{query_field}_str': Cast(JSONF(query_field), models.TextField())})
            for q in values:
                if q == 'None':
                    filt |= Q(**{f'{query_field}__isnull': True})
                else:
                    filt |= Q(**{f'{query_field}_str': q})
        statistics = statistics.filter(filt)

    # groupby
    if groupby == 'country' or groupby in fields_to_select:
        fields = OrderedDict()
        fields['groupby'] = groupby.title()
        fields['n_accounts'] = 'Num'
        fields['avg_score'] = 'Avg'
        medals = {m['name']: m for m in options.get('medals', [])}
        if 'medal' in contest_fields:
            for medal in settings.ORDERED_MEDALS_:
                fields[f'n_{medal}'] = medals.get(medal, {}).get('value', medal[0].upper())
        if 'advanced' in contest_fields:
            fields['n_advanced'] = 'Adv'

        orderby = [f for f in orderby if f.lstrip('-') in fields] or ['-n_accounts', '-avg_score']

        if groupby == 'languages':
            _, before_params = statistics.query.sql_with_params()
            querysets = []
            for problem in problems:
                key = get_problem_key(problem)
                field = f'addition__problems__{key}__language'
                score = f'addition__problems__{key}__result'
                qs = statistics \
                    .filter(**{f'{field}__isnull': False}) \
                    .annotate(language=Cast(JSONF(field), models.TextField())) \
                    .annotate(score=Case(
                        When(**{f'{score}__startswith': '+'}, then=1),
                        When(**{f'{score}__startswith': '-'}, then=0),
                        When(**{f'{score}__startswith': '?'}, then=0),
                        default=Cast(JSONF(score), models.FloatField()),
                        output_field=models.FloatField(),
                    )) \
                    .annotate(sid=F('pk'))
                querysets.append(qs)
            merge_statistics = querysets[0].union(*querysets[1:], all=True)
            language_query, language_params = merge_statistics.query.sql_with_params()
            field = 'solving'
            statistics = statistics.annotate(groupby=F(field))
        elif groupby == 'country':
            if '_countries' in contest_fields:
                statistics = statistics.annotate(
                    country=RawSQL('''json_array_elements((("addition" ->> '_countries'))::json)::jsonb''', []))
                field = 'country'
            else:
                field = 'account__country'
            statistics = statistics.annotate(groupby=F(field))
        else:
            field = f'addition__{groupby}'
            types = contest.info.get('fields_types', {}).get(groupby, [])
            if len(types) == 1 and types[0] == 'int':
                field_type = models.IntegerField()
            else:
                field_type = models.TextField()
            statistics = statistics.annotate(groupby=Cast(JSONF(field), field_type))

        statistics = statistics.order_by('groupby')
        statistics = statistics.values('groupby')
        statistics = statistics.annotate(n_accounts=Count('id'))
        statistics = statistics.annotate(avg_score=Avg('solving'))

        if 'medal' in contest_fields:
            for medal in settings.ORDERED_MEDALS_:
                n_medal = f'n_{medal}'
                statistics = statistics.annotate(**{
                    f'{n_medal}': Count(Case(When(addition__medal__iexact=medal, then=1)))
                })
        if 'advanced' in contest_fields:
            statistics = statistics.annotate(n_advanced=Count(
                Case(
                    When(addition__advanced=True, then=1),
                    When(~Q(addition__advanced=False) & ~Q(addition__advanced=''), then=1),
                )
            ))

        statistics = statistics.order_by(*orderby)

        if groupby == 'languages':
            query, params = statistics.query.sql_with_params()
            query = query.replace(f'"ranking_statistics"."{field}" AS "groupby"', '"language" AS "groupby"')
            query = query.replace(f'GROUP BY "ranking_statistics"."{field}"', 'GROUP BY "language"')
            query = query.replace(f'"ranking_statistics".', '')
            query = query.replace(f'AVG("solving") AS "avg_score"', 'AVG("score") AS "avg_score"')
            query = query.replace(f'COUNT("id") AS "n_accounts"', 'COUNT("sid") AS "n_accounts"')
            query = re.sub('FROM "ranking_statistics".*GROUP BY', f'FROM ({language_query}) t1 GROUP BY', query)
            params = params[:-len(before_params)] + language_params
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                columns = [col[0] for col in cursor.description]
                statistics = [dict(zip(columns, row)) for row in cursor.fetchall()]
                statistics = ListAsQueryset(statistics)

        problems = []
        labels_groupby = {
            'n_accounts': 'Number of participants',
            'avg_score': 'Average score',
            'n_advanced': 'Number of advanced',
        }
        for medal in settings.ORDERED_MEDALS_:
            labels_groupby[f'n_{medal}'] = 'Number of ' + medals.get(medal, {}).get('value', medal)
        num_rows_groupby = statistics.count()
        map_colors_groupby = {s['groupby']: idx for idx, s in enumerate(statistics)}
    else:
        groupby = 'none'
        labels_groupby = None
        num_rows_groupby = None
        map_colors_groupby = None

    context = {
        'data_1st_u': data_1st_u,
        'participants_info': participants_info,
        'standings_options': options,
        'mod_penalty': mod_penalty,
        'colored_by_group_score': mod_penalty or options.get('colored_by_group_score'),
        'contest': contest,
        'statistics': statistics,
        'problems': problems,
        'params': params,
        'fields': fields,
        'divisions_order': divisions_order,
        'has_country': has_country,
        'per_page': per_page,
        'with_row_num': with_row_num,
        'merge_problems': merge_problems,
        'fields_to_select': fields_to_select,
        'truncatechars_name_problem': 10 * (2 if merge_problems else 1),
        'with_detail': with_detail,
        'groupby': groupby,
        'pie_limit_rows_groupby': 50,
        'labels_groupby': labels_groupby,
        'num_rows_groupby': num_rows_groupby,
        'map_colors_groupby': map_colors_groupby,
        'advance': contest.info.get('advance'),
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


def solutions(request, sid, problem_key):
    statistic = get_object_or_404(Statistics.objects.select_related('account', 'contest'), pk=sid)
    problems = statistic.addition.get('problems', {})
    if problem_key not in problems:
        return HttpResponseNotFound()

    contest_problems = statistic.contest.info['problems']
    if 'division' in contest_problems:
        contest_problems = contest_problems['division'][statistic.addition['division']]
    for problem in contest_problems:
        if get_problem_key(problem) == problem_key:
            break
    else:
        problem = None

    stat = problems[problem_key]

    return render(
        request,
        'solution-source.html' if request.is_ajax() else 'solution.html',
        {
            'is_modal': request.is_ajax(),
            'statistic': statistic,
            'account': statistic.account,
            'contest': statistic.contest,
            'problem': problem,
            'stat': stat,
            'fields': ['time', 'status', 'language'],
        })


@login_required
@xframe_options_exempt
def action(request):
    user = request.user
    error = None
    message = None

    try:
        action = request.POST['action']
        if action == 'reset_contest_statistic_timing':
            contest_id = request.POST['cid']
            contest = Contest.objects.get(pk=contest_id)
            if not user.has_perm('reset_contest_statistic_timing'):
                error = 'No permission.'
            else:
                message = f'Updated timing.statistic = {contest.timing.statistic}.'
                contest.timing.statistic = None
                contest.timing.save()
        else:
            error = 'Unknown action'
    except Exception as e:
        error = str(e)

    if error is not None:
        ret = {'status': 'error', 'message': error}
    else:
        ret = {'status': 'ok', 'message': message}
    return JsonResponse(ret)
