import colorsys
import copy
import re
from collections import OrderedDict

import arrow
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection, models
from django.db.models import Avg, Case, Count, Exists, F, OuterRef, Prefetch, Q, Value, When
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, window
from django.http import HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from el_pagination.decorators import page_template, page_templates
from ratelimit.decorators import ratelimit
from sql_util.utils import Exists as SubqueryExists

from clist.models import Contest, Resource
from clist.templatetags.extras import get_country_name, get_problem_short, query_transform, slug, toint
from clist.views import get_timeformat, get_timezone
from ranking.management.modules.common import FailOnGetResponse
from ranking.management.modules.excepts import ExceptionParseStandings
from ranking.models import Account, Module, Statistics
from tg.models import Chat
from true_coders.models import Coder, CoderList, Party
from true_coders.views import get_ratings_data
from utils.colors import get_n_colors
from utils.json_field import JSONF
from utils.list_as_queryset import ListAsQueryset
from utils.regex import get_iregex_filter


@page_template('standings_list_paging.html')
def standings_list(request, template='standings_list.html', extra_context=None):
    contests = Contest.objects \
        .select_related('timing') \
        .select_related('resource') \
        .annotate(has_module=Exists(Module.objects.filter(resource=OuterRef('resource_id')))) \
        .filter(Q(n_statistics__gt=0) | Q(end_time__lte=timezone.now())) \
        .order_by('-end_time', 'pk')

    all_standings = False
    if request.user.is_authenticated:
        all_standings = request.user.coder.settings.get('all_standings')

    switch = 'switch' in request.GET
    if bool(all_standings) == bool(switch):
        contests = contests.filter(n_statistics__gt=0, has_module=True)
        if request.user.is_authenticated:
            contests = contests.filter(request.user.coder.get_contest_filter(['list']))

    search = request.GET.get('search')
    if search is not None:
        contests = contests.filter(get_iregex_filter(
            search,
            'title', 'host', 'resource__host',
            mapping={
                'name': {'fields': ['title__iregex']},
                'slug': {'fields': ['slug']},
                'resource': {'fields': ['host', 'resource__host'], 'suff': '__iregex'},
                'writer': {'fields': ['info__writers__contains']},
                'coder': {'fields': ['statistics__account__coders__username']},
                'account': {'fields': ['statistics__account__key', 'statistics__account__name'], 'suff': '__iregex'},
                'stage': {'fields': ['stage'], 'suff': '__isnull', 'func': lambda v: False},
                'medal': {'fields': ['info__standings__medals'], 'suff': '__isnull', 'func': lambda v: False},
            },
            logger=request.logger,
        ))

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        contests = contests.filter(resource_id__in=resources)
        resources = list(Resource.objects.filter(pk__in=resources))

    if request.user.is_authenticated:
        contests = contests.prefetch_related(Prefetch(
            'statistics_set',
            to_attr='stats',
            queryset=Statistics.objects.filter(account__coders=request.user.coder),
        ))

    active_stage_query = Q(stage__isnull=False, end_time__gt=timezone.now())
    context = {
        'stages': contests.filter(active_stage_query),
        'contests': contests.exclude(active_stage_query),
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'all_standings': all_standings,
        'switch': switch,
        'params': {
            'resources': resources,
        },
    }

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


def _standings_highlight(statistics, options):
    ret = {}
    data_1st_u = options.get('1st_u')
    participants_info = {}
    if data_1st_u:
        lasts = {}
        n_quota = {}
        n_highlight = 0
        last_hl = None
        more_last_hl = None
        quotas = data_1st_u.get('quotas', {})
        more = options.get('more')
        if more:
            more['n'] = 0
        for s in statistics:
            match = re.search(data_1st_u['regex'], s.account.key)
            if not match:
                continue
            k = match.group('key').strip()

            quota = quotas.get(k, data_1st_u.get('default_quota', 1))
            if not quota:
                continue
            add_quota = k in quotas or 'default_quota' in data_1st_u

            solving = s.solving
            penalty = s.addition.get('penalty')

            info = participants_info.setdefault(s.id, {})
            info['search'] = rf'^{k}'

            n_quota[k] = n_quota.get(k, 0) + 1
            if (n_quota[k] > quota or last_hl) and (not more or more['n'] >= more['n_highlight'] or more_last_hl):
                p_info = participants_info.get(lasts.get(k))
                if (not p_info or last_hl and (-last_hl['solving'], last_hl['penalty']) < (-p_info['solving'], p_info['penalty'])):  # noqa
                    p_info = last_hl
                if (not p_info or more_last_hl and (-more_last_hl['solving'], more_last_hl['penalty']) > (-p_info['solving'], p_info['penalty'])):  # noqa
                    p_info = more_last_hl
                info.update({
                    't_solving': p_info['solving'] - solving,
                    't_penalty': p_info['penalty'] - penalty if penalty is not None else None,
                })
            elif n_quota[k] <= quota:
                n_highlight += 1
                lasts[k] = s.id
                info.update({'n': n_highlight, 'solving': solving, 'penalty': penalty})
                if 'n_highlight_prefix' in options:
                    info['prefix'] = options['n_highlight_prefix']
                if add_quota:
                    info['q'] = n_quota[k]
                if n_highlight == options.get('n_highlight'):
                    last_hl = info
            elif more and more['n'] < more['n_highlight']:
                more['n'] += 1
                lasts[k] = s.id
                info.update({'n': more['n'], 'solving': solving, 'penalty': penalty,
                             'n_highlight': more['n_highlight']})
                if 'n_highlight_prefix' in more:
                    info['prefix'] = more['n_highlight_prefix']
                if more['n'] == more['n_highlight']:
                    more_last_hl = info
    elif 'n_highlight' in options:
        if isinstance(options['n_highlight'], int):
            for idx, s in enumerate(statistics[:options['n_highlight']], 1):
                participants_info[s.id] = {'n': idx}
        else:
            n_highlight = copy.deepcopy(options['n_highlight'])
            stats = statistics
            if 'order_by' in n_highlight:
                stats = stats.order_by(*n_highlight['order_by'])
            for s in stats:
                for param in n_highlight['params']:
                    value = s.addition.get(param['field'])
                    if not value:
                        continue
                    if param.get('regex'):
                        match = re.search(param['regex'], value)
                        if not match:
                            continue
                        value = match.group('value')
                    values = param.setdefault('_values', {})
                    counter = values.setdefault(value, {})
                    counter['count'] = counter.get('count', 0) + 1
                    last_score = (s.solving, s.addition.get('penalty'))
                    if counter['count'] <= param['number'] or counter.get('_last') == last_score:
                        participants_info[s.id] = {'highlight': True}
                        ret.setdefault('statistics_ids', set()).add(s.id)
                        if param.get('all'):
                            counter['_last'] = last_score
    ret.update({
        'data_1st_u': data_1st_u,
        'participants_info': participants_info,
    })
    return ret


def _get_order_by(fields):
    order_by = []
    for field in fields:
        if field.startswith('-'):
            desc = True
            field = field[1:]
        else:
            desc = False

        order_field = models.F(field)
        if desc:
            order_field = order_field.desc()
        else:
            order_field = order_field.asc()

        order_by.append(order_field)
    return order_by


@page_templates((
    ('standings_paging.html', 'standings_paging'),
    ('standings_groupby_paging.html', 'groupby_paging'),
))
def standings(request, title_slug=None, contest_id=None, contests_ids=None,
              template='standings.html', extra_context=None):
    context = {}

    groupby = request.GET.get('groupby')
    if groupby == 'none':
        groupby = None

    query = request.GET.copy()
    for k, v in request.GET.items():
        if not v or k == 'groupby' and v == 'none':
            query.pop(k, None)
    if request.GET.urlencode() != query.urlencode():
        query = query.urlencode()
        return redirect(f'{request.path}' + (f'?{query}' if query else ''))

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

    contests = Contest.objects
    to_redirect = False
    contest = None
    if contest_id is not None:
        contest = contests.filter(pk=contest_id).first()
        if title_slug is None:
            to_redirect = True
        else:
            if contest is None or slug(contest.title) != title_slug:
                contest = None
                title_slug += f'-{contest_id}'
    if contest is None and title_slug is not None:
        contests_iterator = contests.filter(slug=title_slug).iterator()

        contest = None
        try:
            contest = next(contests_iterator)
            another = next(contests_iterator)
        except StopIteration:
            another = None
        if contest is None:
            return HttpResponseNotFound()
        if another is None:
            to_redirect = True
        else:
            return redirect(reverse('ranking:standings_list') + f'?search=slug:{title_slug}')
    if contests_ids is not None:
        cids, contests_ids = list(map(toint, contests_ids.split(','))), []
        for cid in cids:
            if cid not in contests_ids:
                contests_ids.append(cid)
        contest = contests.filter(pk=contests_ids[0]).first()
        other_contests = list(contests.filter(pk__in=contests_ids[1:]))
        contests_ids = {c.pk: i for i, c in enumerate([contest] + other_contests, start=1)}
    else:
        other_contests = []
    if contest is None:
        return HttpResponseNotFound()
    if to_redirect:
        query = query_transform(request)
        url = reverse('ranking:standings', kwargs={'title_slug': slug(contest.title), 'contest_id': str(contest.pk)})
        if query:
            query = '?' + query
        return redirect(url + query)

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

    with_row_num = False

    contest_fields = contest.info.get('fields', []).copy()
    fields_types = contest.info.get('fields_types', {}).copy()
    hidden_fields = list(contest.info.get('hidden_fields', []))
    problems = contest.info.get('problems', {})
    inplace_division = '_division_addition' in contest_fields

    if contests_ids:
        statistics = Statistics.objects.filter(contest_id__in=contests_ids)
    else:
        statistics = Statistics.objects.filter(contest=contest)

    options = contest.info.get('standings', {})

    order = None
    resource_standings = contest.resource.info.get('standings', {})
    order = copy.copy(options.get('order', resource_standings.get('order')))
    if order:
        for f in order:
            if f.startswith('addition__') and f.split('__', 1)[1] not in contest_fields:
                order = None
                break
    if order is None:
        order = ['place_as_int', '-solving']

    # fixed fields
    fixed_fields = (
        ('penalty', 'Penalty'),
        ('total_time', 'Time'),
        ('advanced', 'Advance'),
    )
    fixed_fields += tuple(options.get('fixed_fields', []))
    if not with_detail:
        fixed_fields += (('rating_change', 'Rating change'), )

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
    if division == 'any' or contests_ids:
        with_row_num = True
        if 'place_as_int' in order:
            order.remove('place_as_int')
            order.append('place_as_int')
    if 'division' in problems:
        divisions_order = list(problems.get('divisions_order', sorted(contest.info['problems']['division'].keys())))
    elif 'divisions_order' in contest.info:
        divisions_order = contest.info['divisions_order']
    else:
        divisions_order = []
    if division == 'any':
        fixed_fields += (('division', 'Division'),)
    elif divisions_order and division not in divisions_order:
        division = divisions_order[0]
    division_addition = contest.info.get('divisions_addition', {}).get(division, {}).copy()

    if 'team_id' in contest_fields and not groupby:
        order.append('addition__name')
        statistics = statistics.distinct(*[f.lstrip('-') for f in order])

    if inplace_division and division != divisions_order[0]:
        fields_types = division_addition['fields_types']
        statistics = statistics.annotate(addition_replacement=JSONF(f'addition___division_addition__{division}'))
        statistics = statistics.filter(addition_replacement__isnull=False)
        for src, dst in (
            ('place_as_int', f'addition___division_addition__{division}__place'),
            ('solving', f'addition___division_addition__{division}__solving'),
        ):
            for prefix in '', '-':
                psrc = f'{prefix}{src}'
                dsrc = f'{prefix}{dst}'
                if psrc in order:
                    order[order.index(psrc)] = dsrc

    order.append('pk')
    statistics = statistics.order_by(*order)

    fields = OrderedDict()
    for k, v in fixed_fields:
        if k in contest_fields:
            fields[k] = v

    n_highlight_context = _standings_highlight(statistics, options)

    # field to select
    fields_to_select_defaults = {
        'rating': {'options': ['rated', 'unrated'], 'noajax': True, 'nomultiply': True, 'nourl': True},
        'advanced': {'options': ['true', 'false'], 'noajax': True, 'nomultiply': True},
        'highlight': {'options': ['true', 'false'], 'noajax': True, 'nomultiply': True},
    }

    fields_to_select = OrderedDict()
    map_fields_to_select = {'rating_change': 'rating'}
    for f in sorted(contest_fields):
        f = f.strip('_')
        if f.lower() in [
            'institution', 'room', 'affiliation', 'city', 'languages', 'school', 'class', 'job', 'region',
            'rating_change', 'advanced', 'company', 'language', 'league', 'onsite', 'degree', 'university', 'list',
        ]:
            f = map_fields_to_select.get(f, f)
            field_to_select = fields_to_select.setdefault(f, {})
            field_to_select['values'] = [v for v in request.GET.getlist(f) if v]
            field_to_select.update(fields_to_select_defaults.get(f, {}))

    if n_highlight_context.get('statistics_ids'):
        f = 'highlight'
        field_to_select = fields_to_select.setdefault(f, {})
        field_to_select['values'] = [v for v in request.GET.getlist(f) if v]
        field_to_select.update(fields_to_select_defaults.get(f, {}))

    chats = coder.chats.all() if coder else None
    if chats:
        options_values = {c.chat_id: c.title for c in chats}
        fields_to_select['chat'] = {
            'values': [v for v in request.GET.getlist('chat') if v and v in options_values],
            'options': options_values,
            'noajax': True,
            'nogroupby': True,
            'nourl': True,
        }
    chat_options = fields_to_select.get('chat', {}).get('options', {})
    for c in request.GET.getlist('chat'):
        if c and c not in chat_options:
            request.logger.warning(f'You are not a member of chat = {c}')

    lists = coder.my_list_set.all() if coder else None
    if lists:
        options_values = {str(v.uuid): v.name for v in lists}
        fields_to_select['list'] = {
            'values': [v for v in request.GET.getlist('list')],
            'options': options_values,
            'noajax': True,
            'nogroupby': True,
            'nourl': True,
        }

    hidden_fields_values = [v for v in request.GET.getlist('field') if v]
    for v in hidden_fields_values:
        if v not in hidden_fields:
            hidden_fields.append(v)

    addition_fields = (
        division_addition['fields']
        if inplace_division and division != divisions_order[0] else
        contest_fields
    )
    for k in addition_fields:
        if (
            k in fields
            or k in ['problems', 'team_id', 'solved', 'hack', 'challenges', 'url', 'participant_type', 'division']
            or k == 'medal' and ('_medal_title_field' not in contest_fields or inplace_division)
            or 'country' in k and k not in hidden_fields_values
            or k in ['name', 'place', 'solving'] and k not in hidden_fields_values
            or k.startswith('_')
            or k in hidden_fields and k not in hidden_fields_values
        ):
            continue
        if with_detail or k in hidden_fields_values:
            fields[k] = k
        else:
            hidden_fields.append(k)

    for k, field in fields.items():
        if k != field:
            continue
        field = ' '.join(k.split('_'))
        if field and not field[0].isupper():
            field = field.title()
        fields[k] = field

    if hidden_fields:
        fields_to_select['field'] = {
            'values': hidden_fields_values,
            'options': hidden_fields,
            'noajax': True,
            'nogroupby': True,
            'nourl': True,
            'nofilter': True,
        }

    per_page = options.get('per_page', 50)
    if per_page is None:
        per_page = 100500
    elif contest.n_statistics and contest.n_statistics < 500:
        per_page = contest.n_statistics
    per_page_more = 200
    paginate_on_scroll = True
    force_both_scroll = False

    mod_penalty = {}
    first = statistics.first()
    if first and all('time' not in k for k in contest_fields):
        penalty = first.addition.get('penalty')
        if penalty and isinstance(penalty, int) and 'solved' not in first.addition:
            mod_penalty.update({'solving': first.solving, 'penalty': penalty})

    params = {}
    if divisions_order:
        if not inplace_division:
            divisions_order.append('any')
        params['division'] = division
        if 'division' in problems:
            if division == 'any':
                _problems = OrderedDict()
                for div in reversed(divisions_order):
                    for p in problems['division'].get(div, []):
                        k = get_problem_short(p)
                        if k not in _problems:
                            _problems[k] = p
                        else:
                            for f in 'n_accepted', 'n_teams', 'n_partial', 'n_total':
                                if f in p:
                                    _problems[k][f] = _problems[k].get(f, 0) + p[f]
                problems = list(_problems.values())
            else:
                problems = problems['division'][division]
        if division != 'any' and not inplace_division:
            statistics = statistics.filter(addition__division=division)

    for p in problems:
        if 'full_score' in p and isinstance(p['full_score'], (int, float)) and abs(p['full_score'] - 1) > 1e-9:
            mod_penalty = {}
            break

    last = None
    merge_problems = False
    for p in problems:
        if last and (last.get('full_score') or last.get('subname')) and (
            'name' in last and last.get('name') == p.get('name') or
            'group' in last and last.get('group') == p.get('group')
        ):
            merge_problems = True
            last['colspan'] = last.get('colspan', 1) + 1
            p['skip'] = True
        else:
            last = p
            last['colspan'] = 1

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
            cond = get_iregex_filter(search, 'account__key', 'addition__name', logger=request.logger)
            statistics = statistics.filter(cond)

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
    for field, field_to_select in fields_to_select.items():
        values = field_to_select.get('values')
        if not values or field_to_select.get('nofilter'):
            continue
        with_row_num = True
        filt = Q()
        if field == 'languages':
            for lang in values:
                if lang == 'any':
                    filt = Q(**{'addition___languages__isnull': False})
                    break
                filt |= Q(**{'addition___languages__contains': [lang]})
        elif field == 'rating':
            for q in values:
                if q not in field_to_select['options']:
                    continue
                q = q == 'unrated'
                if q:
                    filt |= Q(addition__rating_change__isnull=True) & Q(addition__new_rating__isnull=True)
                else:
                    filt |= Q(addition__rating_change__isnull=False) | Q(addition__new_rating__isnull=False)
        elif field == 'advanced':
            for q in values:
                if q not in field_to_select['options']:
                    continue
                filt |= Q(addition__advanced=q == 'true')
        elif field == 'highlight':
            for q in values:
                if q not in field_to_select['options']:
                    continue
                filt = Q(pk__in=n_highlight_context.get('statistics_ids', {}))
                if q == 'false':
                    filt = ~filt
        elif field == 'chat':
            for q in values:
                if q not in field_to_select['options']:
                    continue
                chat = Chat.objects.filter(chat_id=q, is_group=True).first()
                if chat:
                    filt |= Q(account__coders__in=chat.coders.all())
            # subquery = Chat.objects.filter(coder=OuterRef('account__coders'), is_group=False).values('name')[:1]
            # statistics = statistics.annotate(chat_name=Subquery(subquery))
        elif field == 'list':
            for uuid in values:
                try:
                    coder_list = CoderList.objects.prefetch_related('values').get(uuid=uuid)
                except Exception:
                    request.logger.warning(f'Ignore list with uuid = "{uuid}"')
                    continue
                coders = set()
                accounts = set()
                for v in coder_list.values.all():
                    if v.coder:
                        coders.add(v.coder)
                    if v.account and v.account.resource_id == contest.resource_id:
                        accounts.add(v.account)
                filt |= Q(account__coders__in=coders) | Q(account__in=accounts)
        else:
            query_field = f'addition__{field}'
            statistics = statistics.annotate(**{f'{query_field}_str': Cast(JSONF(query_field), models.TextField())})
            for q in values:
                if q == 'None':
                    filt |= Q(**{f'{query_field}__isnull': True})
                else:
                    filt |= Q(**{f'{query_field}_str': q})
        statistics = statistics.filter(filt)

    # versus statistics
    has_versus = contest.info.get('_has_versus', {}).get('enable')
    versus = request.GET.get('versus')
    versus_data = None
    versus_statistic_id = toint(request.GET.get('id'))
    if has_versus and versus == 'statistics' and versus_statistic_id is not None:
        plugin = contest.resource.plugin.Statistic(contest=contest)
        statistic = get_object_or_404(Statistics.objects.prefetch_related('account'),
                                      contest=contest,
                                      pk=versus_statistic_id)
        versus_status, versus_data = plugin.get_versus(statistic)
        if versus_status:
            statistics = statistics.filter(account__key__in=versus_data['stats'].keys())
            with_row_num = True
        else:
            request.logger.warning(versus_data)
            versus_data = None

    # groupby
    if groupby == 'country' or groupby in fields_to_select:
        statistics = statistics.order_by('pk')

        participants_info = n_highlight_context.get('participants_info')
        n_highlight = options.get('n_highlight')
        advanced_by_participants_info = participants_info and n_highlight and groupby != 'languages'

        fields = OrderedDict()
        fields['groupby'] = groupby.title()
        fields['n_accounts'] = 'Num'
        fields['avg_score'] = 'Avg'
        medals = {m['name']: m for m in options.get('medals', [])}
        if 'medal' in contest_fields:
            for medal in settings.ORDERED_MEDALS_:
                fields[f'n_{medal}'] = medals.get(medal, {}).get('value', medal[0].upper())
        if 'advanced' in contest_fields or advanced_by_participants_info:
            fields['n_advanced'] = 'Adv'

        orderby = [f for f in orderby if f.lstrip('-') in fields] or ['-n_accounts', '-avg_score']

        if groupby == 'languages':
            _, before_params = statistics.query.sql_with_params()
            querysets = []
            for problem in problems:
                key = get_problem_short(problem)
                field = f'addition__problems__{key}__language'
                score = f'addition__problems__{key}__result'
                qs = statistics \
                    .filter(**{f'{field}__isnull': False, f'{score}__isnull': False}) \
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
        elif groupby == 'rating':
            statistics = statistics.annotate(
                groupby=Case(
                    When(addition__rating_change__isnull=False, then=Value('Rated')),
                    default=Value('Unrated'),
                    output_field=models.TextField(),
                )
            )
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
            if 'int' in types:
                field_type = models.IntegerField()
            elif 'float' in types:
                field_type = models.FloatField()
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
        elif advanced_by_participants_info:
            pks = list()
            for pk, info in participants_info.items():
                if 'n' not in info or info['n'] > info.get('n_highlight', n_highlight):
                    continue
                pks.append(pk)
            statistics = statistics.annotate(n_advanced=Count(Case(When(pk__in=set(pks), then=1))))

        statistics = statistics.order_by(*orderby)

        if groupby == 'languages':
            query, sql_params = statistics.query.sql_with_params()
            query = query.replace(f'"ranking_statistics"."{field}" AS "groupby"', '"language" AS "groupby"')
            query = query.replace(f'GROUP BY "ranking_statistics"."{field}"', 'GROUP BY "language"')
            query = query.replace('"ranking_statistics".', '')
            query = query.replace('AVG("solving") AS "avg_score"', 'AVG("score") AS "avg_score"')
            query = query.replace('COUNT("id") AS "n_accounts"', 'COUNT("sid") AS "n_accounts"')
            query = re.sub('FROM "ranking_statistics".*GROUP BY', f'FROM ({language_query}) t1 GROUP BY', query)
            sql_params = sql_params[:-len(before_params)] + language_params
            with connection.cursor() as cursor:
                cursor.execute(query, sql_params)
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

    # find me
    find_me = request.GET.get('find_me')
    if find_me:
        per_page_more = per_page
        if not find_me.isdigit():
            request.logger.error(f'find_me param should be number, found {find_me}')
    if (
        find_me and find_me.isdigit() and
        groupby == 'none' and
        'querystring_key' not in request.GET and
        'standings_paging' not in request.GET
    ):
        my_stat = statistics.annotate(row_number=models.Window(expression=window.RowNumber(),
                                                               order_by=_get_order_by(order)))
        my_stat = my_stat.annotate(statistic_id=F('id'))
        sql_query, sql_params = my_stat.query.sql_with_params()
        my_stat = Statistics.objects.raw(
            '''
            SELECT * FROM ({}) ranking_statistics WHERE "statistic_id" = %s
            '''.format(sql_query),
            [*sql_params, int(find_me)],
        )
        my_stat = list(my_stat)
        if my_stat:
            row_number = my_stat[0].row_number
            if row_number > per_page:
                paging = (row_number - per_page - 1) // per_page_more + 2
                old_mutable = request.GET._mutable
                request.GET._mutable = True
                request.GET['querystring_key'] = 'standings_paging'
                request.GET['standings_paging'] = paging
                request.GET._mutable = old_mutable
            paginate_on_scroll = False
            force_both_scroll = True
        else:
            request.logger.warning(f'Not found find = {find_me}')

    my_statistics = []
    if groupby == 'none' and coder:
        statistics = statistics.annotate(my_stat=SubqueryExists('account__coders', filter=Q(coder=coder)))
        my_statistics = statistics.filter(account__coders=coder).extra(select={'floating': True})
        if my_statistics:
            params['find_me'] = list(my_statistics)[0].pk

    context.update({
        'has_versus': has_versus,
        'versus_data': versus_data,
        'versus_statistic_id': versus_statistic_id,
        'standings_options': options,
        'mod_penalty': mod_penalty,
        'colored_by_group_score': mod_penalty or options.get('colored_by_group_score'),
        'contest': contest,
        'contests_ids': contests_ids,
        'other_contests': other_contests,
        'statistics': statistics,
        'my_statistics': my_statistics,
        'problems': problems,
        'params': params,
        'fields': fields,
        'fields_types': fields_types,
        'divisions_order': divisions_order,
        'has_country': has_country,
        'per_page': per_page,
        'per_page_more': per_page_more,
        'paginate_on_scroll': paginate_on_scroll,
        'force_both_scroll': force_both_scroll,
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
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'with_neighbors': request.GET.get('neighbors') == 'on',
        'with_table_inner_scroll': not request.user_agent.is_mobile,
    })

    context.update(n_highlight_context)

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


@login_required
@ratelimit(key='user', rate='1000/h', block=True)
def solutions(request, sid, problem_key):
    statistic = get_object_or_404(Statistics.objects.select_related('account', 'contest', 'contest__resource'), pk=sid)
    problems = statistic.addition.get('problems', {})
    if problem_key not in problems:
        return HttpResponseNotFound()

    contest_problems = statistic.contest.info['problems']
    if 'division' in contest_problems:
        contest_problems = contest_problems['division'][statistic.addition['division']]
    for problem in contest_problems:
        if get_problem_short(problem) == problem_key:
            break
    else:
        problem = None

    stat = problems[problem_key]

    if 'solution' not in stat:
        if stat.get('external_solution'):
            plugin = statistic.contest.resource.plugin
            try:
                source_code = plugin.Statistic.get_source_code(statistic.contest, stat)
                stat.update(source_code)
            except (NotImplementedError, ExceptionParseStandings, FailOnGetResponse):
                return HttpResponseNotFound()
        else:
            return HttpResponseNotFound()

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


def get_versus_data(request, query, fields_to_select):
    opponents = [whos.split(',') for whos in query.split('/vs/')]

    base_filter = Q()
    rating = fields_to_select['rating']['values']
    if rating:
        for q in rating:
            if q not in fields_to_select['rating']['options']:
                continue
            q = q == 'unrated'
            if q:
                base_filter &= Q(addition__rating_change__isnull=True) & Q(addition__new_rating__isnull=True)
            else:
                base_filter &= Q(addition__rating_change__isnull=False) | Q(addition__new_rating__isnull=False)

    daterange = request.GET.get('daterange')
    if daterange:
        date_from, date_to = [arrow.get(x).datetime for x in daterange.split(' - ')]
        base_filter &= Q(contest__start_time__gte=date_from, contest__end_time__lte=date_to) | Q(contest__info__fields__contains='_rating_data')  # noqa
    else:
        date_from, date_to = None, None

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        base_filter &= Q(contest__resource__in=resources)

    filters = []
    urls = []
    for idx, whos in enumerate(opponents):
        filt = Q()
        us = []

        n_accounts = 0
        for who in whos:
            n_accounts += ':' in who

        for who in whos:
            url = None
            if ':' in who:
                host, key = who.split(':', 1)
                account = Account.objects.filter(Q(resource__host=host) | Q(resource__short_host=host), key=key).first()
                if not account:
                    request.logger.warning(f'Not found account {who}')
                else:
                    filt |= Q(account=account)
                    url = reverse('coder:account', kwargs={'key': account.key, 'host': account.resource.host})
            else:
                coder = Coder.objects.filter(username=who).first()
                if not coder:
                    request.logger.warning(f'Not found coder {who}')
                else:
                    if n_accounts == 0:
                        filt |= Q(account__coders=coder)
                    else:
                        accounts = list(coder.account_set.all())
                        filt |= Q(account__in=accounts)
                    url = reverse('coder:profile', args=[coder.username])
            us.append(url)
        if not filt:
            filt = Q(pk=-1)
        urls.append(us)
        filters.append(base_filter & filt)

    infos = []
    medal_contests_ids = set()
    for filt in filters:
        qs = Statistics.objects.filter(filt, place__isnull=False)

        ratings_data = get_ratings_data(request=request, statistics=qs, date_from=date_from, date_to=date_to)

        infos.append({
            'score': 0,
            'contests': {s.contest_id: s for s in qs},
            'divisions': {(s.contest_id, s.addition.get('division')) for s in qs},
            'ratings': ratings_data,
        })
        for s in qs:
            if s.addition.get('medal'):
                medal_contests_ids.add(s.contest_id)

    intersection = set.intersection(*[info['divisions'] for info in infos])
    contests_ids = {cid for cid, div in intersection}

    return {
        'infos': infos,
        'opponents': opponents,
        'urls': urls,
        'filters': filters,
        'contests_ids': contests_ids,
        'medal_contests_ids': medal_contests_ids,
    }


def versus(request, query):

    if request.GET.get('coder'):
        coder = get_object_or_404(Coder, pk=request.GET.get('coder'))
        return redirect(f'{request.path}vs/{coder.username}')

    if request.GET.get('remove'):
        idx = int(request.GET.get('remove'))
        parts = query.split('/vs/')
        if 0 <= idx < len(parts):
            parts = parts[:idx] + parts[idx + 1:]
        query = '/vs/'.join(parts)
        return redirect(reverse('ranking:versus', args=[query]))

    # filtration data
    params = {}

    fields_to_select = {}

    for data in [
        {'field': 'rating', 'options': ['rated', 'unrated']},
        {'field': 'score_in_row', 'options': ['show', 'hide'], 'title': 'score'},
        {'field': 'medal', 'options': ['yes', 'no']},
    ]:
        field = data.pop('field')
        fields_to_select[field] = {
            'noajax': True,
            'nomultiply': True,
            'nourl': True,
            'nogroupby': True,
            'values': [v for v in request.GET.getlist(field) if v],
        }
        fields_to_select[field].update(data)

    versus_data = get_versus_data(request, query, fields_to_select)

    # filter contests
    contests = Contest.visible.filter(pk__in=versus_data['contests_ids']).order_by('-end_time')
    contests = contests.select_related('resource')

    search = request.GET.get('search')
    if search is not None:
        with_medal = False

        def set_medal(v):
            nonlocal with_medal
            with_medal = True
            return False

        contests_filter = get_iregex_filter(search,
                                            'title', 'host', 'resource__host',
                                            mapping={
                                                'contest': {'fields': ['title__iregex']},
                                                'resource': {'fields': ['host__iregex']},
                                                'slug': {'fields': ['slug']},
                                                'writer': {'fields': ['info__writers__contains']},
                                                'medal': {'fields': ['info__standings__medals'],
                                                          'suff': '__isnull',
                                                          'func': set_medal},
                                            },
                                            logger=request.logger)
        if with_medal:
            contests_filter |= Q(pk__in=versus_data['medal_contests_ids'])
        contests = contests.filter(contests_filter)

    medal = request.GET.get('medal')
    if medal:
        contests_filter = Q(info__standings__medals__isnull=False)
        contests_filter |= Q(pk__in=versus_data['medal_contests_ids'])
        if medal == 'no':
            contests_filter = ~contests_filter
        contests = contests.filter(contests_filter)

    daterange = request.GET.get('daterange')
    if daterange:
        date_from, date_to = [arrow.get(x).datetime for x in daterange.split(' - ')]
        contests = contests.filter(start_time__gte=date_from, end_time__lte=date_to)

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        resources = list(Resource.objects.filter(pk__in=resources))
        params['resources'] = resources
        rids = set([r.pk for r in resources])
        contests = contests.filter(resource_id__in=rids)

    # scoring by contests
    scores = versus_data.setdefault('scores', {})
    for contest in reversed(contests):
        best = None
        indices = []
        for idx, info in enumerate(versus_data['infos']):
            stat = info['contests'][contest.pk]
            score = (stat.place_as_int, -stat.solving)
            if best is None or score < best:
                best = score
                indices = []
            if score == best:
                indices.append(idx)
        for idx in indices:
            info = versus_data['infos'][idx]
            info['score'] += 1
            setattr(info['contests'][contest.pk], 'scored_', True)
        scores[contest.pk] = {
            'score': [info['score'] for info in versus_data['infos']],
            'indices': indices,
        }

    ratings_resources = None
    for idx, info in enumerate(versus_data['infos']):
        rdata = info['ratings']['data']
        rdata_resources = {k: sum([len(d) for d in v['data']]) for k, v in rdata['resources'].items()}
        if ratings_resources is None:
            ratings_resources = rdata_resources
        else:
            ratings_resources = {
                k: v + ratings_resources[k]
                for k, v in rdata_resources.items() if k in ratings_resources
            }
    ratings_resources = sorted([(v, k) for k, v in ratings_resources.items()], reverse=True)

    ratings_data = {'resources': {}}
    ratings_dates = []

    ignore_colors = {}
    rdata = versus_data['infos'][0]['ratings']['data']
    for _, resource in ratings_resources:
        rinfo = rdata['resources'][resource]
        for color in rinfo['colors']:
            H, S, L = color['hsl']
            rgb = colorsys.hls_to_rgb(H, L, S)
            ignore_colors[color['hex_rgb']] = rgb
    ignore_colors = list(ignore_colors.values())

    datasets_colors = get_n_colors(n=len(versus_data['infos']), ignore_colors=ignore_colors)
    for idx, info in enumerate(versus_data['infos']):
        rdata = info['ratings']['data']
        for _, resource in ratings_resources:
            rinfo = rdata['resources'][resource]
            rinfo.pop('highest', None)
            resource_info = ratings_data['resources'].setdefault(resource, {
                'data': [],
                'colors': rinfo.pop('colors'),
                'min': rinfo['min'],
                'max': rinfo['max'],
                'point_radius': 0,
                'point_hit_radius': 5,
                'border_width': 1,
                'outline': True,
                'tooltip_mode': 'nearest',
                'datasets': {
                    'colors': datasets_colors,
                    'labels': versus_data['opponents'],
                },
                'x_axes_unit': rinfo.pop('x_axes_unit', None),
            })
            rinfo_data = rinfo.pop('data')
            resource_info['data'].extend(rinfo_data)
            resource_info['min'] = min(resource_info['min'], rinfo.pop('min'))
            resource_info['max'] = max(resource_info['max'], rinfo.pop('max'))
            for data in rinfo_data:
                for stat in data:
                    stat['date'] = str(stat['date'])
                    ratings_dates.append(stat['date'])
            resource_info.update(rinfo)

    ratings_data['dates'] = list(sorted(set(ratings_dates)))
    versus_data['ratings'] = ratings_data

    context = {
        'contests': contests,
        'versus_data': versus_data,
        'params': params,
        'fields_to_select': fields_to_select,
        'rated': 'rated' in fields_to_select['rating']['values'],
        'scored': 'show' in fields_to_select['score_in_row']['values'],
    }
    return render(request, 'versus.html', context)


def make_versus(request):
    n_versus = 0
    n_versus_mapping = {}
    opponents = OrderedDict()
    for key in request.GET.keys():
        if not key.startswith('coder') and not key.startswith('account'):
            continue

        values = [v for v in request.GET.getlist(key) if v]
        if not values:
            continue
        values = list(map(int, values))
        if key.startswith('coder'):
            values = Coder.objects.filter(pk__in=values)
        else:
            values = Account.objects.filter(pk__in=values).select_related('resource')

        if key not in n_versus_mapping:
            n_versus_mapping[key] = n_versus
            n_versus += 1
        versus_idx = n_versus_mapping[key]

        if '_' in key:
            key, *_ = key.split('_')
        key = f'{key}_{versus_idx}'

        opponents[key] = values

    whos = []
    for key, values in opponents.items():
        if key.startswith('coder'):
            who = ','.join([c.username for c in values])
        elif key.startswith('account'):
            who = ','.join([f'{a.resource.short_host or a.resource.host}:{a.key}' for a in values])
        else:
            request.logger.warning(f'Unknown opponents type {key}')
            continue
        whos.append(who)
    url = reverse('ranking:versus', args=['/vs/'.join(whos)]) if len(whos) > 1 else None

    context = {
        'url': url,
        'opponents': opponents,
    }
    return render(request, 'make_versus.html', context)
