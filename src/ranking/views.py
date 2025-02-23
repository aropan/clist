import bisect
import colorsys
import copy
import hashlib
import re
from collections import OrderedDict, defaultdict
from datetime import timedelta
from functools import reduce

import arrow
import yaml
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Avg, Case, Count, Exists, F, OuterRef, Prefetch, Q, Subquery, Value, When
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, window
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.clickjacking import xframe_options_exempt
from django_ratelimit.decorators import ratelimit
from el_pagination.decorators import page_template, page_templates
from sql_util.utils import Exists as SubqueryExists

from clist.models import Contest, ContestSeries, Resource
from clist.templatetags.extras import (allowed_redirect, as_number, format_time, get_country_name, get_item,
                                       get_problem_short, get_problem_title, get_standings_divisions_order,
                                       has_update_statistics_permission, is_ip_field, is_optional_yes, is_private_field,
                                       is_reject, is_solved, is_yes, redirect_login, time_in_seconds,
                                       timestamp_to_datetime)
from clist.templatetags.extras import timezone as set_timezone
from clist.templatetags.extras import toint, url_transform
from clist.views import get_group_list, get_timeformat, get_timezone
from pyclist.decorators import context_pagination, extra_context_without_pagination, inject_contest
from pyclist.middleware import RedirectException
from ranking.management.modules.excepts import ExceptionParseStandings, FailOnGetResponse, ProxyLimitReached
from ranking.models import (Account, AccountRenaming, Finalist, FinalistResourceInfo, Module, Stage, Statistics,
                            VirtualStart)
from ranking.utils import get_participation_contests
from tg.models import Chat
from true_coders.models import Coder, CoderList, ListGroup, Party
from true_coders.views import get_ratings_data
from utils.chart import make_bins, make_histogram
from utils.colors import get_n_colors
from utils.json_field import JSONF
from utils.mathutils import max_with_none, min_with_none
from utils.rating import get_rating
from utils.regex import get_iregex_filter


@page_template('standings_list_paging.html')
@extra_context_without_pagination('clist.view_full_table')
@context_pagination()
def standings_list(request, template='standings_list.html'):
    contests = (
        Contest.objects.annotate_favorite(request.user)
        .annotate_active_executions()
        .select_related('resource', 'stage')
        .annotate(has_module=Exists(Module.objects.filter(resource=OuterRef('resource_id'))))
        .filter(Q(n_statistics__gt=0) | Q(end_time__lte=timezone.now()))
        .order_by('-end_time', '-id')
    )

    all_standings = False
    if request.user.is_authenticated:
        coder = request.user.coder
        all_standings = coder.settings.get('all_standings')
    else:
        coder = None

    switch = request.GET.get('switch')
    if bool(all_standings) == bool(switch) and switch != 'all' or switch == 'parsed':
        contests = contests.filter(Q(invisible=False) | Q(stage__isnull=False))
        contests = contests.filter(n_statistics__gt=0, has_module=True)
        if request.user.is_authenticated:
            contests = contests.filter(coder.get_contest_filter(['list']))

    favorite_value = request.GET.get('favorite')
    if favorite_value == 'on':
        contests = contests.filter(is_favorite=True)
    elif favorite_value == 'off':
        contests = contests.filter(is_favorite=False)

    if participation := request.GET.get('participation'):
        participation_operator, participation_contests = get_participation_contests(request, participation)
        contests = getattr(contests, participation_operator)(pk__in=participation_contests)

    search = request.GET.get('search')
    if search is not None:
        contests = contests.filter(get_iregex_filter(
            search,
            'title', 'url', 'host', 'resource__host',
            mapping={
                'name': {'fields': ['title__iregex']},
                'slug': {'fields': ['slug']},
                'resource': {'fields': ['host', 'resource__host'], 'suff': '__iregex'},
                'writer': {'fields': ['info__writers__contains']},
                'coder': {'fields': ['statistics__account__coders__username']},
                'account': {'fields': ['statistics__account__key', 'statistics__account__name'], 'suff': '__iregex'},
                'stage': {'fields': ['stage'], 'suff': '__isnull', 'func': lambda v: v not in settings.YES_},
                'kind': {'fields': ['kind'], 'suff': '__isnull', 'func': lambda v: v not in settings.YES_},
                'medal': {'fields': ['with_medals'], 'func': lambda v: v in settings.YES_},
                'related_set': {'fields': ['related_set'], 'suff': '__isnull',
                                'func': lambda v: v not in settings.YES_},
                'advance': {'fields': ['with_advance'], 'func': lambda v: v in settings.YES_},
                'year': {'fields': ['start_time__year', 'end_time__year']},
                'invisible': {'fields': ['invisible'], 'func': lambda v: v in settings.YES_},
                'has_problems': {'fields': ['n_problems'], 'suff': '__isnull',
                                 'func': lambda v: v not in settings.YES_},
                'n_problems': {'fields': ['n_problems'], 'suff': ''},
            },
            logger=request.logger,
        ))

    with_submissions = is_yes(request.GET.get('with_submissions'))
    if with_submissions:
        contests = contests.filter(has_submissions=True)

    resources = request.get_resources()
    if resources:
        contests = contests.filter(resource__in=resources)

    more_fields = []
    if request.user.has_perm('clist.view_more_fields'):
        more_fields = [f for f in request.GET.getlist('more') if f]
        for field in more_fields:
            if '=' not in field:
                continue
            key, value = field.split('=')
            value = yaml.safe_load(value)
            contests = contests.filter(**{key: value})

    if request.user.is_authenticated:
        contests = contests.prefetch_related(Prefetch(
            'statistics_set',
            to_attr='stats',
            queryset=Statistics.objects.filter(account__coders=request.user.coder),
        ))

    active_stage_query = Q(stage__isnull=False, end_time__gt=timezone.now())
    stages = contests.filter(active_stage_query)
    contests = contests.exclude(active_stage_query)

    series = [s for s in request.GET.getlist('series') if s]
    if series:
        if 'all' in series:
            series = list(ContestSeries.objects.all())
        else:
            series = list(ContestSeries.objects.filter(slug__in=series))
        link_series = request.GET.get('link_series') in settings.YES_
        link_series = link_series and request.user.has_perm('clist.change_contestseries')
        link_series = link_series and len(series) == 1
        if link_series:
            contests.update(series=series[0])
        stages = stages.filter(series_id__in={s.pk for s in series})
        contests = contests.filter(series_id__in={s.pk for s in series})

    with_medal_scores = len(series) == 1
    if with_medal_scores and is_yes(request.GET.get('with_medal_scores')):
        ordering = ('contest__start_time', 'contest_id', 'addition__medal')
        qs = Statistics.objects.distinct(*ordering)
        qs = qs.order_by(*ordering, 'solving')
        qs = contests.prefetch_related(Prefetch('statistics_set', to_attr='medal_scores', queryset=qs))
        qs = qs.order_by('start_time')

        medal_scores_chart = dict(
            field='medal_scores',
            type='scatter',
            show_line=True,
            legend_position='right',
            x_type='time',
            mode='x',
            hover_mode='x',
        )

        datas = medal_scores_chart.setdefault('datas', {})
        titles = medal_scores_chart.setdefault('titles', {})
        subtitles = medal_scores_chart.setdefault('subtitles', {})
        urls = medal_scores_chart.setdefault('urls', {})
        last_values = {}
        for contest in qs:
            full_score = contest.full_score
            contest_title = contest.start_time.strftime('%Y-%m-%d')
            if not full_score:
                continue
            for medal_score in contest.medal_scores:
                medal = medal_score.addition.get('medal')
                if not medal:
                    continue
                medal_datas = datas.setdefault(medal, {})
                medal_value = medal_score.solving / full_score
                medal_datas[contest.end_time.isoformat()] = medal_value
                titles.setdefault(medal, []).append(contest_title)
                urls.setdefault(medal, []).append(contest.actual_url)

                subtitle = 'Score: {:.2f}'.format(medal_score.solving)
                if medal in last_values:
                    delta = medal_value / last_values[medal] - 1
                    print(contest.start_time, medal_value, last_values[medal], medal_value / last_values[medal], delta)
                    subtitle += f' ({delta:+.2%})'
                last_values[medal] = medal_value
                subtitles.setdefault(medal, []).append(subtitle)

        medal_fields = list(datas.keys())
        medal_names = ['bronze', 'silver', 'gold']
        for rev_order in medal_names:
            if rev_order in medal_fields:
                medal_fields.remove(rev_order)
                medal_fields.insert(0, rev_order)
        medal_scores_chart['fields'] = medal_fields
        medal_scores_chart['hidden'] = set([f for f in medal_fields if f not in medal_names])
    else:
        medal_scores_chart = None

    context = {
        'navbar_admin_model': Contest,
        'stages': stages,
        'contests': contests,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'all_standings': all_standings,
        'switch': switch,
        'params': {
            'resources': resources,
            'series': series,
            'more_fields': more_fields,
            'with_medal_scores': with_medal_scores,
        },
        'medal_scores_chart': medal_scores_chart,
    }

    action = request.POST.get('action')
    if action == 'reparse':
        if not request.user.has_perm('clist.change_contest'):
            return HttpResponseForbidden('Permission denied')
        n_updated = 0
        n_total = 0
        for contest in contests:
            n_updated += contest.require_statistics_update()
            n_total += 1
        return JsonResponse({'status': 'ok', 'message': f'Updated {n_updated} of {n_total} contests to reparse'})

    if get_group_list(request) and len(resources) != 1:
        running_contest_query = Q(end_time__gt=timezone.now())
        running_contests = contests.filter(running_contest_query)
        contests = contests.exclude(running_contest_query)

        running_contests_ = []
        grouped_running_contests = defaultdict(list)
        for contest in reversed(running_contests):
            if contest.resource not in grouped_running_contests:
                running_contests_.append(contest)
            grouped_running_contests[contest.resource].append(contest)
        for values in grouped_running_contests.values():
            values.reverse()
            values.pop(-1)
        running_contests = running_contests_

        context.update({
            'grouped_running_contests': grouped_running_contests,
            'running_contests': running_contests,
            'contests': contests,
        })

    return template, context


def _standings_highlight(contest, statistics, options):
    contest_penalty_time = min((timezone.now() - contest.start_time).total_seconds(), contest.duration_in_secs) // 60

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
        force_highlight = options.get('force_highlight')
        if more:
            more['n'] = 0
        for s in statistics:
            if s.place_as_int is None:
                continue
            string = s.addition.get(data_1st_u['field']) if 'field' in data_1st_u else s.account.key
            if string is None:
                continue
            match = re.search(data_1st_u['regex'], string)
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
            info['search'] = rf'regex:^{k}'
            info['first_u_key'] = k
            info['first_u_quota'] = quota

            n_quota[k] = n_quota.get(k, 0) + 1
            if (n_quota[k] > quota or last_hl) and (not more or more['n'] >= more['n_highlight'] or more_last_hl):
                p_info = participants_info.get(lasts.get(k))
                if (not p_info or last_hl and (-last_hl['solving'], last_hl['penalty']) < (-p_info['solving'], p_info['penalty'])):  # noqa
                    p_info = last_hl
                if (not p_info or more_last_hl and (-more_last_hl['solving'], more_last_hl['penalty']) > (-p_info['solving'], p_info['penalty'])):  # noqa
                    p_info = more_last_hl

                if n_quota[k] <= quota:
                    n_highlight += 1

                info.update({
                    'n': n_highlight,
                    'out_of_highlight': True,
                    't_solving': p_info['solving'] - solving,
                    't_penalty': (
                        p_info['penalty'] - penalty - round((p_info['solving'] - solving) * contest_penalty_time)
                        if penalty is not None else None
                    ),
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

            if n_quota[k] <= quota and force_highlight and k in force_highlight:
                info['highlight'] = True
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


def standings_charts(request, context):
    default_n_bins = 20
    contest = context['contest']
    problems = context['problems']
    statistics = context['statistics']
    timeline = context['contest_timeline']
    contests_timelines = context['contests_timelines'] or {}
    params = context['params']

    statistics = statistics.prefetch_related(None)
    statistics = statistics.select_related(None)
    statistics = statistics.select_related('account')

    find_me = request.GET.get('find_me')
    my_stat_pk = toint(find_me) if find_me else params.get('find_me')

    charts = []

    mapping_fields_values = dict(
        new_rating='_ratings',
        old_rating='_ratings',
    )
    fields_values = defaultdict(list)
    fields_types = defaultdict(set)
    problems_values = defaultdict(list)
    problems_scores_values = defaultdict(list)
    problems_scoring_values = defaultdict(list)
    top_values = []
    scores_values = []
    int_scores = True
    my_values = {}
    is_stage = hasattr(contest, 'stage') and contest.stage is not None
    is_scoring = contest.standings_kind in {'cf', 'scoring'}

    full_scores = dict()
    for problem in problems:
        if 'full_score' not in problem:
            continue
        short = get_problem_short(problem)
        full_scores[short] = problem['full_score']

    for stat in statistics:
        if not is_stage and stat.skip_in_stats:
            continue

        addition = stat.addition
        name = addition['name'] if context.get('name_instead_key') and addition.get('name') else stat.account.key

        is_my_stat = stat.pk == my_stat_pk
        if is_my_stat:
            my_values['__stat'] = stat
            my_values['__label'] = name

        if stat.solving is not None:
            int_scores = int_scores and abs(round(stat.solving) - stat.solving) < 1e-9
            scores_values.append(stat.solving)
            if is_my_stat:
                my_values['score'] = stat.solving

        for field, value in addition.items():
            if field == 'rating_change':
                value = toint(value)
            if value is None:
                continue
            if field in mapping_fields_values:
                fields_values[mapping_fields_values[field]].append(value)
            fields_types[field].add(type(value))
            fields_values[field].append(value)
            if is_my_stat and field not in ['score', 'problems']:
                my_values[field] = value

        stat_timeline = contests_timelines.get(stat.contest_id, timeline)
        is_top = len(top_values) < 5 or is_my_stat

        scores_info = {'name': name, 'place': stat.place_as_int, 'key': stat.account.key, 'times': [], 'scores': []}
        for key, info in addition.get('problems', {}).items():
            result = info.get('result')
            if not is_solved(result):
                continue

            is_binary = info.get('binary') or str(result).startswith('+')
            if is_binary:
                result = full_scores.get(key, 1)
            result = as_number(result)
            problems_scores_values[key].append(result)

            if 'time_in_seconds' in info:
                time = info['time_in_seconds']
            else:
                time = info.get('time')
                if time is None:
                    continue
                time = time_in_seconds(stat_timeline, time)

            rel_time = time
            if context.get('relative_problem_time') and 'absolute_time' in info:
                rel_time = time_in_seconds(stat_timeline, info['absolute_time'])
            problems_scoring_values[key].append((time, result))

            if is_top:
                scores_info['times'].append(rel_time)
                scores_info['scores'].append(result)

            if info.get('partial'):
                continue

            problems_values[key].append(time)
            if is_my_stat:
                my_values.setdefault('problems', {})[key] = time

        if is_top and scores_info['times']:
            top_values.append(scores_info)

    if scores_values:
        if int_scores:
            scores_values = [round(x) for x in scores_values]
        hist, bins = make_histogram(scores_values, n_bins=default_n_bins)
        scores_chart = dict(
            field='scores',
            bins=bins,
            shift_my_value=int_scores and bins[-1] - bins[0] == len(bins) - 1,
            data=[{'bin': b, 'value': v} for v, b in zip(hist, bins)],
            my_value=my_values.get('score'),
        )
        charts.append(scores_chart)

    if context.get('relative_problem_time'):
        total_problem_time = max([max(v) for v in problems_values.values()], default=0) + 1
    else:
        total_problem_time = contest.duration_in_secs

    if top_values:
        top_bins = make_bins(0, contest.duration_in_secs, n_bins=default_n_bins)
        top_chart = dict(
            field='top_scores',
            type='scatter',
            fields=[],
            labels={},
            bins=top_bins,
            datas={},
            cubic_interpolation=True,
            point_radius=2,
            border_width=2,
            show_line=True,
            legend_position='right',
            x_ticks_time_rounding=timeline.get('penalty_rounding', 'floor-minute'),
        )
        for scores_info in top_values:
            field = scores_info['key']
            datas = top_chart['datas'].setdefault(field, {0: 0})
            val = 0
            for t, d in sorted(zip(scores_info['times'], scores_info['scores'])):
                val += d
                datas[t] = val
            top_chart['fields'].append(field)
            top_chart['labels'][field] = f"{scores_info['place'] or '-'}. {scores_info['name']}"
        charts.append(top_chart)

    def timeline_format(t):
        rounding = timeline.get('penalty_rounding', 'floor-minute')
        if rounding == 'floor-minute':
            t = int(t / 60)
            ret = f'{t // 60}:{t % 60:02d}'
        else:
            if rounding == 'floor-second':
                t = int(t)
            ret = f'{t // 60 // 60}:{t // 60 % 60:02d}:{t % 60:02d}'
        return ret

    problems_bins = make_bins(0, total_problem_time, n_bins=default_n_bins)
    problems_chart = dict(
        field='solved_problems',
        type='line',
        accumulate=True,
        fields=[],
        labels={},
        bins=problems_bins,
        data=[{'bin': timeline_format(b)} for b in problems_bins[:-1]],
        cubic_interpolation=True,
        point_radius=0,
        border_width=2,
        legend_position='right',
    )
    total_values = []
    my_data = []
    for problem in problems:
        short = get_problem_short(problem)
        values = problems_values.get(short, [])
        total_values.extend(values)
        hist, _ = make_histogram(values=values, bins=problems_bins)
        for val, d in zip(hist, problems_chart['data']):
            d[short] = val
        problems_chart['fields'].append(short)
        problems_chart['labels'][short] = get_problem_title(problem)

        if short in my_values.get('problems', {}):
            idx = bisect.bisect(problems_bins, my_values['problems'][short]) - 1
            if idx < len(problems_chart['data']):
                my_data.append({'x': problems_bins[idx], 'y': problems_chart['data'][idx][short], 'field': short})
    if my_data:
        my_data.sort(key=lambda d: (d['x'], -d['y']))
        for d in my_data:
            d['x'] = timeline_format(d['x'])
        problems_chart['my_dataset'] = {
            'data': my_data,
            'point_radius': 4,
            'point_hover_radius': 8,
            'label': my_values['__label'],
        }
    if problems_values:
        charts.append(problems_chart)

    total_scoring_values = []
    if is_scoring and problems_scoring_values:
        problems_scoring_chart = copy.deepcopy(problems_chart)
        problems_scoring_chart.update(dict(
            field='scoring_problems',
            my_dataset=None,
        ))

        for problem in problems:
            short = get_problem_short(problem)
            values = problems_scoring_values.get(short,  [])
            total_scoring_values.extend(values)

            deltas = [v[1] for v in values]
            values = [v[0] for v in values]
            hist, _ = make_histogram(values=values, deltas=deltas, bins=problems_bins)
            for val, d in zip(hist, problems_scoring_chart['data']):
                d[short] = val

        charts.append(problems_scoring_chart)

    total_solved_chart = copy.deepcopy(problems_chart)
    total_solved_chart.update(dict(
        field='total_solved',
        fields=False,
        labels=False,
        my_dataset=None,
        accumulate=False,
    ))
    hist, _ = make_histogram(values=total_values, bins=problems_bins)
    for val, d in zip(hist, total_solved_chart['data']):
        d['value'] = val
    if total_values:
        charts.append(total_solved_chart)

    if is_scoring and total_scoring_values:
        total_scoring_chart = copy.deepcopy(problems_chart)
        total_scoring_chart.update(dict(
            field='total_scoring',
            fields=False,
            labels=False,
            my_dataset=None,
        ))
        values = [v[0] for v in total_scoring_values]
        deltas = [v[1] for v in total_scoring_values]
        hist, _ = make_histogram(values=values, deltas=deltas, bins=problems_bins)
        for val, d in zip(hist, total_scoring_chart['data']):
            d['value'] = val
        charts.append(total_scoring_chart)

    if is_scoring and problems_scores_values:
        total_scores_values = []
        for values in problems_scores_values.values():
            total_scores_values.extend(values)

        _, problems_scores_bins = make_histogram(values=total_scores_values, n_bins=default_n_bins)
        problems_scores_chart = copy.deepcopy(problems_chart)
        problems_scores_chart.update(dict(
            field='problems_scores',
            type='line',
            bins=problems_scores_bins,
            data=[{'bin': b} for b in problems_scores_bins[:-1]],
            my_dataset=None,
        ))
        for problem in problems:
            short = get_problem_short(problem)
            values = problems_scores_values.get(short, [])
            hist, _ = make_histogram(values, bins=problems_scores_bins)
            for val, d in zip(hist, problems_scores_chart['data']):
                d[short] = val
        charts.append(problems_scores_chart)

    for field in contest.info.get('fields', []):
        types = fields_types.get(field)
        if field.startswith('_') or not types or not fields_values[field]:
            continue
        if not all(t in [int, float] for t in types):
            continue
        field_type = float if float in types else int
        field_values = [field_type(v) for v in fields_values[field]]

        if field in mapping_fields_values:
            values = fields_values[mapping_fields_values[field]]
            bins = make_bins(min(values), max(values), n_bins=default_n_bins)
            hist, bins = make_histogram(field_values, bins=bins)
        else:
            hist, bins = make_histogram(field_values, n_bins=default_n_bins)

        chart = dict(
            field=field,
            bins=bins,
            shift_my_value=field_type is int and bins[-1] - bins[0] == len(bins) - 1,
            data=[{'bin': b, 'value': v} for v, b in zip(hist, bins)],
            my_value=my_values.get(field),
        )

        field_types = context['fields_types'].get(field, [])
        if 'timestamp' in field_types:
            for d in chart['data']:
                t = timestamp_to_datetime(d['bin'])
                t = set_timezone(t, context['timezone'])
                t = format_time(t, context['timeformat'])
                d['bin'] = t

        charts.append(chart)

    context['charts'] = charts


def render_standings_paging(contest, statistics, with_detail=True):
    contest_fields = contest.info.get('fields', [])

    n_total = None
    if isinstance(statistics, list):
        per_page = contest.standings_per_page
        if per_page > len(statistics):
            n_total = len(statistics)
            statistics = statistics[:per_page]
        statistics = Statistics.objects.filter(pk__in=statistics)

    order = contest.get_statistics_order()
    statistics = statistics.order_by(*order)

    inplace_division = '_division_addition' in contest_fields
    divisions_order = get_standings_divisions_order(contest)
    division = divisions_order[0] if divisions_order else None
    if division:
        if inplace_division:
            field = f'addition___division_addition__{division}'
            statistics = statistics.filter(**{f'{field}__isnull': False})
        else:
            statistics = statistics.filter(addition__division=division)

    problems = get_standings_problems(contest, division)

    fields = get_standings_fields(contest, division=division, with_detail=with_detail)

    statistics = statistics.prefetch_related('account')

    mod_penalty = get_standings_mod_penalty(contest, division, problems, statistics)
    colored_by_group_score = contest.info.get('standings', {}).get('colored_by_group_score')

    has_country = (
        'country' in contest_fields or
        '_countries' in contest_fields or
        statistics.filter(account__country__isnull=False).exists()
    )

    context = {
        'request': HttpRequest(),
        'contest': contest,
        'division': division,
        'statistics': statistics,
        'problems': problems,
        'fields': fields,
        'without_pagination': True,
        'my_statistics': [],
        'contest_timeline': contest.get_timeline_info(),
        'has_country': has_country,
        'with_detail': with_detail,
        'per_page': contest.standings_per_page,
        'per_page_more': 0,
        'mod_penalty': mod_penalty,
        'colored_by_group_score': mod_penalty or colored_by_group_score,
        'virtual_start': None,
        'virtual_start_statistics': None,
        'with_virtual_start': False,
        'unspecified_place': settings.STANDINGS_UNSPECIFIED_PLACE,
    }

    options = contest.info.get('standings', {})
    data_1st_u = options.get('1st_u')
    if data_1st_u:
        n_highlight_context = _standings_highlight(contest, contest.statistics_set.order_by(*order), options)
        context.update(n_highlight_context)

    return {
        'page': get_template('standings_paging.html').render(context),
        'total': n_total or statistics.count(),
    }


def update_standings_socket(contest, statistics):
    rendered = render_standings_paging(contest, statistics)
    channel_layer = get_channel_layer()
    context = {
        'type': 'standings',
        'rows': rendered['page'],
        'n_total': rendered['total'],
        'time_percentage': contest.time_percentage,
    }
    async_to_sync(channel_layer.group_send)(contest.channel_group_name, context)


def get_standings_mod_penalty(contest, division, problems, statistics):
    for p in problems:
        if 'full_score' in p and isinstance(p['full_score'], (int, float)) and abs(p['full_score'] - 1) > 1e-9:
            return None
    contest_fields = contest.info.get('fields', [])
    if contest.duration_in_secs and all('time' not in k for k in contest_fields):
        if division and division != 'any':
            statistics = statistics.filter(addition__division=division)
        first = statistics.first()
        if first:
            penalty = first.addition.get('penalty')
            if penalty and isinstance(penalty, int) and 'solved' not in first.addition:
                return {'solving': first.solving, 'penalty': penalty}
    return None


def get_standings_problems(contest, division):
    divisions_order = get_standings_divisions_order(contest)
    problems = contest.info.get('problems', {})
    if 'division' in problems:
        if division == 'any':
            _problems = OrderedDict()
            for div in reversed(divisions_order):
                for p in problems['division'].get(div, []):
                    k = get_problem_short(p)
                    if k not in _problems:
                        _problems[k] = p
                    else:
                        _pk = _problems[k]
                        for f in 'n_accepted', 'n_teams', 'n_partial', 'n_total':
                            if f in p:
                                _pk[f] = _pk.get(f, 0) + p[f]

                        if 'first_ac' in p:
                            in_seconds = p['first_ac']['in_seconds']
                            if 'first_ac' not in _pk or in_seconds + 1e-9 < _pk['first_ac']['in_seconds']:
                                _pk['first_ac'] = copy.deepcopy(p['first_ac'])
                            elif 'first_ac' in _pk and in_seconds - 1e-9 < _pk['first_ac']['in_seconds']:
                                _pk['first_ac']['accounts'].extend(p['first_ac']['accounts'])

                        if 'full_score' in p:
                            fs = str(_pk.get('full_score', ''))
                            if fs:
                                fs += ' '
                            fs += str(p['full_score'])
                            _pk['full_score'] = fs
            problems = list(_problems.values())
        else:
            problems = problems['division'][division]
    if division:
        problems = [p for p in problems if division not in p.get('skip_for_divisions', [])]
    problems = [p for p in problems if not p.get('skip_in_standings')]
    return problems


def get_standings_fields(contest, division, with_detail, hidden_fields=None, hidden_fields_values=None,
                         view_private_fields=None):
    contest_fields = contest.info.get('fields', [])
    fields_values = contest.info.get('fields_values', {})
    options = contest.info.get('standings', {})
    divisions_order = get_standings_divisions_order(contest)
    division_addition = contest.info.get('divisions_addition', {}).get(division, {})
    inplace_division = '_division_addition' in contest_fields

    fixed_fields = (
        'penalty',
        ('total_time', 'Time'),
        ('advanced', 'Adv'),
    )
    fixed_fields += tuple(options.get('fixed_fields', []))
    if not with_detail:
        fixed_fields += ('rating_change',)
    if division == 'any':
        fixed_fields += ('division',)

    fields = OrderedDict()
    for k in fixed_fields:
        if isinstance(k, str):
            v = k
        else:
            k, v = k
        if k in contest_fields:
            fields[k] = v

    division_addition_fields = inplace_division and divisions_order and division != divisions_order[0]
    addition_fields = division_addition.get('fields', contest_fields) if division_addition_fields else contest_fields
    special_fields = ['team_id', 'participant_type', 'division', 'medal', 'raw_rating', 'medal_percentage']
    special_fields.extend(settings.ADDITION_HIDE_FIELDS_)
    if hidden_fields is None:
        hidden_fields = list(contest.info.get('hidden_fields', []))
    hidden_fields_values = hidden_fields_values or []

    predicted_fields = ['predicted_rating_change', 'predicted_new_rating', 'predicted_rating_perf']
    if contest.rating_prediction_hash:
        addition_fields = addition_fields + predicted_fields
        hidden_fields.extend(predicted_fields)

    addition_fields.extend(settings.STANDINGS_STATISTIC_FIELDS)
    hidden_fields.extend(settings.STANDINGS_STATISTIC_FIELDS)

    for k in hidden_fields_values + addition_fields:
        is_private_k = k.startswith('_')
        if (
            k in fields
            or k in special_fields
            or not is_private_k and 'country' in k and k not in hidden_fields_values
            or k in ['name', 'place', 'solving'] and k not in hidden_fields_values
            or is_private_k and not view_private_fields
            or k in hidden_fields and k not in hidden_fields_values and k not in fields_values
        ):
            continue
        if not is_private_k and with_detail or k in hidden_fields_values or k in fields_values:
            fields[k] = k
        if k not in hidden_fields:
            hidden_fields.append(k)

    if contest.has_rating_prediction and with_detail:
        for field in predicted_fields:
            if field not in fields and 'rating_change' not in field:
                fields[field] = field

    for k, field in fields.items():
        if k != field:
            continue
        field = ' '.join(k.split('_'))
        if field and not field[0].isupper():
            field = field.title()
        fields[k] = field
    return fields


def get_advancing_contests(contest):
    ret = set()

    def rec(contest):
        if contest in ret:
            return
        ret.add(contest)

        stage = getattr(contest, 'stage', None)
        if not stage:
            return
        exclude_stages = stage.score_params.get('advances', {}).get('exclude_stages', [])
        for s in Stage.objects.filter(pk__in=exclude_stages):
            rec(s.contest)

    rec(contest)
    return ret


@page_templates((
    ('standings_paging.html', 'standings_paging'),
    ('standings_groupby_paging.html', 'groupby_paging'),
))
@inject_contest()
def standings(request, contest, other_contests=None, template='standings.html', extra_context=None):
    context = {}

    contests_timelines = dict()
    contests_ids = dict()
    if other_contests is not None:
        for i, c in enumerate([contest] + other_contests, start=1):
            contests_ids[c.pk] = i
            contests_timelines[c.pk] = c.get_timeline_info()

    groupby = request.GET.get('groupby')
    if groupby == 'none':
        groupby = None

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
            return allowed_redirect(f'{request.path}?{query.urlencode()}')

    find_me = request.GET.get('find_me')
    if find_me:
        if not find_me.isdigit():
            request.logger.error(f'find_me param should be number, found {find_me}')
            find_me = False
        else:
            find_me = int(find_me)

    with_detail = is_optional_yes(request.GET.get('detail'))
    with_solution = is_optional_yes(request.GET.get('solution'))
    with_autoreload = is_optional_yes(request.GET.get('autoreload'))
    if request.user.is_authenticated:
        coder = request.user.coder
        with_detail = coder.update_or_get_setting('standings_with_detail', with_detail)
        with_solution = coder.update_or_get_setting('standings_with_solution', with_solution)
        with_autoreload = coder.update_or_get_setting('standings_with_autoreload', with_autoreload)
    else:
        coder = None
    with_detail = with_detail if with_detail is not None else settings.STANDINGS_WITH_DETAIL_DEFAULT
    with_solution = with_solution if with_solution is not None else settings.STANDINGS_WITH_SOLUTION_DEFAULT
    with_autoreload = with_autoreload if with_autoreload is not None else settings.STANDINGS_WITH_AUTORELOAD_DEFAULT

    with_row_num = False

    contest_fields = contest.info.get('fields', []).copy()
    fields_types = contest.info.get('fields_types', {}).copy()
    hidden_fields = list(contest.info.get('hidden_fields', []))
    hidden_fields_values = [v for v in request.GET.getlist('field') if v]
    inplace_division = '_division_addition' in contest_fields

    if contests_ids:
        statistics = Statistics.objects.filter(contest_id__in=contests_ids)
    else:
        statistics = Statistics.objects.filter(contest=contest)

    options = copy.deepcopy(contest.info.get('standings', {}))

    per_page = 50 if contests_ids else contest.standings_per_page
    per_page_more = per_page if find_me else 200

    order = contest.get_statistics_order()

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
    divisions_order = get_standings_divisions_order(contest)

    if division != 'any' and divisions_order and division not in divisions_order:
        if find_me:
            values = statistics.filter(pk=find_me).values('addition__division')
        elif coder:
            values = statistics.filter(account__coders=coder).values('addition__division')
        else:
            values = None
        if values:
            values = [v['addition__division'] for v in values if v['addition__division'] in divisions_order]
        if values:
            division = values[0]
        if division not in divisions_order:
            division = divisions_order[0]
        if not values and values is not None and not inplace_division:
            division = 'any'
    if division == 'any' or contests_ids:
        with_row_num = True
        if 'penalty' in contest_fields:
            order.append('addition__penalty')
        if 'place_as_int' in order:
            order.remove('place_as_int')
            order.append('place_as_int')

    division_addition = contest.info.get('divisions_addition', {}).get(division, {})

    # FIXME extra per_page
    if (
        contest.n_statistics
        and (
            contest.n_statistics <= settings.STANDINGS_SMALL_N_STATISTICS and 'team_id' in contest_fields
            or contest.info.get('grouped_team')
        ) and not groupby
    ):
        if 'team_id' in contest_fields:
            order.append('addition__team_id')
        else:
            order.append('addition__name')
        statistics = statistics.distinct(*[f.lstrip('-') for f in order])

    if inplace_division and division != divisions_order[0]:
        fields_types = division_addition.get('fields_types', fields_types)
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

    view_private_fields = request.has_contest_perm('view_private_fields', contest)
    fields = get_standings_fields(
        contest,
        division=division,
        with_detail=with_detail,
        hidden_fields=hidden_fields,
        hidden_fields_values=hidden_fields_values,
        view_private_fields=view_private_fields,
    )
    if 'global_rating' in hidden_fields_values:
        fields['new_global_rating'] = 'new_global_rating'
        fields['global_rating_change'] = 'global_rating_change'
        hidden_fields.append('global_rating')
        hidden_fields_values.remove('global_rating')
    if request.user.has_perm('view_hidden_fields', contest.resource):
        for v in hidden_fields_values:
            if v not in hidden_fields and v not in fields:
                fields[v] = v
                hidden_fields.append(v)

    if n_advanced := request.GET.get('n_advanced'):
        if n_advanced.isdigit() and int(n_advanced) and 'n_highlight' in options:
            options['n_highlight'] = int(n_advanced)
    n_highlight_context = _standings_highlight(contest, statistics, options) if not contests_ids else {}

    # field to select
    fields_to_select_defaults = {
        'rating': {'options': ['rated', 'unrated'], 'noajax': True, 'nomultiply': True, 'nourl': True},
        'advanced': {'options': ['true', 'false'], 'noajax': True, 'nomultiply': True,
                     'extra_url': url_transform(request, advanced_accounts='true')},
        'ghost': {'options': ['true', 'false'], 'noajax': True, 'nomultiply': True},
        'highlight': {'options': ['true', 'false'], 'noajax': True, 'nomultiply': True},
    }

    fields_to_select = OrderedDict()
    map_fields_to_select = {'rating_change': 'rating'}

    def add_field_to_select(f):
        f = map_fields_to_select.get(f, f)
        field_to_select = fields_to_select.setdefault(f, {})
        field_to_select['values'] = request.get_filtered_list(f)
        if is_ip_field(f):
            field_to_select['icon'] = 'secret'
        field_to_select.update(fields_to_select_defaults.get(f, {}))

    for f in sorted(contest_fields):
        is_hidden_field = f.startswith('_')
        f = f.strip('_')
        fk = f.lower()
        if (
            is_hidden_field and fk in ['languages', 'verdicts']
            or fk in [
                'institution', 'room', 'affiliation', 'city', 'school', 'class', 'job', 'region', 'location',
                'rating_change', 'advanced', 'company', 'language', 'league', 'onsite',
                'degree', 'university', 'list', 'group', 'group_ex', 'college', 'ghost', 'badge',
            ]
            or view_private_fields and is_private_field(fk) and is_hidden_field and f'_{fk}' in fields
        ):
            add_field_to_select(f)

    if contest.with_advance and 'advanced' not in fields_to_select:
        add_field_to_select('advanced')

    if n_highlight_context.get('statistics_ids'):
        add_field_to_select('highlight')

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

    list_uuids = [v for v in request.GET.getlist('list') if v]
    coder_lists, list_uuids = CoderList.filter_for_coder_and_uuids(coder=coder, uuids=list_uuids, logger=request.logger)
    if coder_lists:
        options_values = {str(v.uuid): v.name for v in coder_lists}
        list_uuids = [uuid for uuid in list_uuids if uuid in options_values]
        fields_to_select['list'] = {
            'values': list_uuids, 'options': options_values,
            'noajax': True, 'nogroupby': True, 'nourl': True,
        }

    if contest.is_rated and 'global_rating' not in hidden_fields and settings.ENABLE_GLOBAL_RATING_:
        hidden_fields.append('global_rating')
    if hidden_fields:
        fields_to_select['field'] = {
            'values': hidden_fields_values,
            'options': hidden_fields,
            'noajax': True,
            'nogroupby': True,
            'nourl': True,
            'nofilter': True,
        }

    paginate_on_scroll = True
    force_both_scroll = False

    enable_timeline = False
    timeline = None
    if contest.duration_in_secs:
        first = statistics.first()
        if first:
            first_problems = list(first.addition.get('problems', {}).values())
            enable_timeline = all(not is_reject(p) for p in first_problems) or any('time' in p for p in first_problems)
    if enable_timeline and 'timeline' in request.GET:
        timeline = request.GET.get('timeline') or 'show'
        if timeline and re.match(r'^(show|unfreezing|play|[01]|[01]?(?:\.[0-9]+)?|[0-9]+(?::[0-9]+){2})$', timeline):
            if ':' in timeline:
                val = reduce(lambda x, y: x * 60 + int(y), timeline.split(':'), 0)
                timeline = f'{val / contest.duration_in_secs:.6f}'
        else:
            timeline = None
    contest_timeline = contest.get_timeline_info()
    enable_timeline = enable_timeline and contest_timeline

    problems = get_standings_problems(contest, division)
    mod_penalty = get_standings_mod_penalty(contest, division, problems, statistics)
    freeze_duration_factor = options.get('freeze_duration_factor', settings.STANDINGS_FREEZE_DURATION_FACTOR_DEFAULT)
    freeze_duration_factor = request.GET.get('t_freeze', freeze_duration_factor)
    freeze_duration = (mod_penalty or 't_freeze' in request.GET) and freeze_duration_factor
    if freeze_duration and contest.is_over():
        t_freeze = str(freeze_duration_factor)
        if ':' in str(freeze_duration_factor):
            val = reduce(lambda x, y: x * 60 + int(y), str(freeze_duration_factor).split(':'), 0)
            freeze_duration_factor = val / contest.duration_in_secs
        else:
            freeze_duration_factor = as_number(freeze_duration_factor)
        freeze_duration = contest.duration_in_secs * freeze_duration_factor
    else:
        t_freeze = None
        freeze_duration = None

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

    params = {}

    # filter by division
    if divisions_order:
        params['division'] = division
        if not inplace_division:
            divisions_order.append('any')
        if divisions_order and division != 'any':
            if inplace_division:
                field = f'addition___division_addition__{division}'
                statistics = statistics.filter(**{f'{field}__isnull': False})
            else:
                statistics = statistics.filter(addition__division=division)

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
        elif search.startswith('score:'):
            _, score = search.split(':')
            statistics = statistics.filter(solving=score)
        else:
            if search.startswith('regex:'):
                search = search[search.index(':') + 1:]
                suffix = '__regex'
            else:
                suffix = '__icontains'

            cond = get_iregex_filter(search, 'account__key', 'account__name', suffix=suffix,
                                     logger=request.logger)  # FIXME: add addition__name
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

    # add resource accounts info
    resources = request.get_resources()
    if resources:
        params['resources'] = resources
        resource_coders = Coder.objects.prefetch_related(Prefetch(
            'account_set',
            to_attr='resource_accounts',
            queryset=Account.objects.filter(resource__in=resources),
        ))
        statistics = statistics.prefetch_related(Prefetch(
            'account__coders',
            to_attr='resource_coders',
            queryset=resource_coders,
        ))

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
        elif field == 'verdicts':
            for verdict in values:
                if verdict == 'any':
                    filt = Q(**{'addition___verdicts__isnull': False})
                    break
                filt |= Q(**{'addition___verdicts__contains': [verdict]})
        elif field == 'badge':
            if 'badge' not in fields:
                fields['badge'] = 'Badge'
            for badge in values:
                if badge == 'any':
                    filt = Q(**{'addition__badge__isnull': False})
                    break
                if badge == 'None':
                    filt |= Q(**{'addition__badge__isnull': True})
                else:
                    filt |= Q(**{'addition__badge__title': badge})
        elif is_ip_field(field):
            field = '_' + field
            types = fields_types.get(field)
            for value in values:
                key = f'addition__{field}'
                if 'list' in types:
                    key += '__contains'
                if 'int' in types or 'float' in types:
                    value = as_number(value)
                filt |= Q(**{key: value})
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
                filt |= Q(advanced=q == 'true')
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
                    filt |= Q(account__coders__in=chat.coders.all()) | Q(account__in=chat.accounts.all())
            # subquery = Chat.objects.filter(coder=OuterRef('account__coders'), is_group=False).values('name')[:1]
            # statistics = statistics.annotate(chat_name=Subquery(subquery))
        elif field == 'list':
            if values:
                groups = ListGroup.objects.filter(coder_list__uuid__in=values, coder_list__custom_names=True,
                                                  name__isnull=False)
                groups = groups.filter(Q(values__account=OuterRef('account')) |
                                       Q(values__coder__account=OuterRef('account')))
                statistics = statistics.annotate(value_instead_key=Subquery(groups.values('name')[:1]))
            coders, accounts = CoderList.coders_and_accounts_ids(uuids=values, coder=coder)
            filt |= Q(account__coders__in=coders) | Q(account__in=accounts)
        else:
            query_field = f'addition__{field}'
            statistics = statistics.annotate(**{f'{query_field}_str': JSONF(query_field)})
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
    versus_statistic_id = toint(request.GET.get('versus_id'))
    if has_versus and versus == 'statistics' and versus_statistic_id is not None:
        plugin = contest.resource.plugin.Statistic(contest=contest)
        statistic = get_object_or_404(Statistics.objects.prefetch_related('account'),
                                      contest=contest,
                                      pk=versus_statistic_id)
        versus_status, versus_data = plugin.get_versus(statistic)
        if versus_status:
            statistics = statistics.filter(account__resource=contest.resource,
                                           account__key__in=versus_data['stats'].keys())
            with_row_num = True
        else:
            request.logger.warning(versus_data)
            versus_data = None

    # groupby
    if groupby == 'country' or groupby in fields_to_select:
        statistics = statistics.order_by('pk')

        participants_info = n_highlight_context.get('participants_info')
        n_highlight = options.get('n_highlight')
        advanced_by_participants_info = participants_info and n_highlight

        fields = OrderedDict()
        fields['groupby'] = groupby.title()
        fields['n_accounts'] = 'Num'
        fields['avg_score'] = 'Avg'
        medals = {m['name']: m for m in options.get('medals', [])}
        if 'medal' in contest_fields:
            for medal in settings.ORDERED_MEDALS_:
                fields[f'n_{medal}'] = medals.get(medal, {}).get('value', medal[0].upper())
        if contest.with_advance or advanced_by_participants_info:
            fields['n_advanced'] = 'Adv'

        default_orderby = not orderby
        orderby = [f for f in orderby if f.lstrip('-') in fields] or ['-n_accounts', '-avg_score']
        field = groupby
        if is_private_field(field):
            field = f'_{field}'
        types = fields_types.get(field, [])

        if groupby == 'rating':
            statistics = statistics.annotate(
                groupby=Case(
                    When(addition__rating_change__isnull=False, then=Value('Rated')),
                    default=Value('Unrated'),
                    output_field=models.TextField(),
                )
            )
        elif groupby == 'country':
            if '_countries' in contest_fields:
                raw_sql = '''json_array_elements((("addition" ->> '_countries'))::json)::jsonb'''
                statistics = statistics.annotate(country=RawSQL(raw_sql, []))
                field = 'country'
            else:
                field = 'account__country'
            statistics = statistics.annotate(groupby=F(field))
        elif is_ip_field(groupby) and 'list' in types:
            raw_sql = f'''json_array_elements((("addition" ->> '_{groupby}'))::json)'''
            raw_sql += ''' #>>'{}' '''  # trim double quotes
            field = groupby
            statistics = statistics.annotate(**{field: RawSQL(raw_sql, [])}).annotate(groupby=F(field))
        elif groupby == 'languages':
            raw_sql = '''json_array_elements((("addition" ->> '_languages'))::json)'''
            raw_sql += ''' #>>'{}' '''  # trim double quotes
            field = 'language'
            statistics = statistics.annotate(language=RawSQL(raw_sql, [])).annotate(groupby=F(field))
        elif groupby == 'verdicts':
            raw_sql = '''json_array_elements((("addition" ->> '_verdicts'))::json)'''
            raw_sql += ''' #>>'{}' '''  # trim double quotes
            field = 'verdict'
            statistics = statistics.annotate(verdict=RawSQL(raw_sql, [])).annotate(groupby=F(field))
        elif groupby == 'badge':
            statistics = statistics.annotate(groupby=JSONF('addition__badge__title'))
        elif groupby == 'advanced':
            statistics = statistics.annotate(groupby=Cast(F('advanced'), models.TextField()))
        else:
            field = f'addition__{field}'
            value = JSONF(field)
            if 'int' in types:
                value = Cast(value, models.IntegerField())
            elif 'float' in types:
                value = Cast(value, models.FloatField())
            statistics = statistics.annotate(groupby=value)

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

        if contest.with_advance:
            statistics = statistics.annotate(n_advanced=Count(Case(When(advanced=True, then=1))))
        elif advanced_by_participants_info:
            pks = list()
            for pk, info in participants_info.items():
                if 'n' not in info or info['n'] > info.get('n_highlight', n_highlight):
                    continue
                pks.append(pk)
            statistics = statistics.annotate(n_advanced=Count(Case(When(pk__in=set(pks), then=1))))

        if default_orderby and groupby == 'league' and 'leagues' in contest.info:
            league_mapping = {league: idx for idx, league in enumerate(contest.info['leagues'])}
            statistics = statistics.annotate(
                league_order=Case(
                    *[When(groupby=k, then=Value(v)) for k, v in league_mapping.items()],
                    default=Value(len(league_mapping)),
                    output_field=models.IntegerField(),
                )
            )
            orderby = ['league_order'] + orderby
        statistics = statistics.order_by(*orderby)

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
    if find_me and groupby == 'none':
        find_me_stat = statistics.annotate(row_number=models.Window(expression=window.RowNumber(),
                                                                    order_by=_get_order_by(order)))
        find_me_stat = find_me_stat.annotate(statistic_id=F('id'))
        sql_query, sql_params = find_me_stat.query.sql_with_params()
        find_me_stat = Statistics.objects.raw(
            '''
            SELECT * FROM ({}) ranking_statistics WHERE "statistic_id" = %s
            '''.format(sql_query),
            [*sql_params, find_me],
        )
        find_me_stat = list(find_me_stat)
        if find_me_stat:
            find_me_stat = find_me_stat[0]
            row_number = find_me_stat.row_number
            paging_free = 'querystring_key' not in request.GET and 'standings_paging' not in request.GET
            if paging_free and row_number > per_page:
                paging = (row_number - per_page - 1) // per_page_more + 2
                old_mutable = request.GET._mutable
                request.GET._mutable = True
                request.GET['querystring_key'] = 'standings_paging'
                request.GET['standings_paging'] = paging
                request.GET._mutable = old_mutable
                force_both_scroll = True
            paginate_on_scroll = False
        else:
            request.logger.warning(f'Not found find = {find_me}')
    else:
        find_me_stat = None

    my_statistics = []
    my_stat = None
    if groupby == 'none' and coder:
        statistics = statistics.annotate(my_stat=SubqueryExists('account__coders', filter=Q(coder=coder)))
        my_statistics = statistics.filter(account__coders=coder).extra(select={'floating': True})
        if my_statistics:
            my_stat = list(my_statistics)[0]
            params['find_me'] = my_stat.pk
            if (
                my_stat.place_as_int and
                find_me_stat and
                (not find_me_stat.place_as_int or find_me_stat.place_as_int > my_stat.place_as_int)
            ):
                context['my_statistics_rev'] = True

    # field_instead_key
    if field_instead_key := request.GET.get('field_instead_key'):
        if field_instead_key in contest_fields:
            context['field_instead_key'] = f'addition__{field_instead_key}'

    relative_problem_time = contest.resource.info.get('standings', {}).get('relative_problem_time')
    relative_problem_time = contest.info.get('standings', {}).get('relative_problem_time', relative_problem_time)
    context['relative_problem_time'] = relative_problem_time

    name_instead_key = contest.resource.info.get('standings', {}).get('name_instead_key')
    name_instead_key = contest.info.get('standings', {}).get('name_instead_key', name_instead_key)
    context['name_instead_key'] = name_instead_key

    virtual_start = VirtualStart.objects.filter(contest=contest, coder=coder).first()
    with_virtual_start = bool(virtual_start and virtual_start.is_active() and enable_timeline)
    if with_virtual_start:
        timeline = None

    inner_scroll = not request.user_agent.is_mobile
    is_charts = is_yes(request.GET.get('charts'))

    hide_problems = set()
    if my_stat and contest.hide_unsolved_standings_problems and not contest.is_over():
        my_stat_problems = my_stat.addition.get('problems', {})
        for problem in problems:
            short = get_problem_short(problem)
            if not is_solved(my_stat_problems.get(short)):
                hide_problems.add(short)

    context.update({
        'has_versus': has_versus,
        'versus_data': versus_data,
        'versus_statistic_id': versus_statistic_id,
        'standings_options': options,
        'has_alternative_result': with_detail and options.get('alternative_result_field'),
        'mod_penalty': mod_penalty,
        'freeze_duration': freeze_duration,
        't_freeze': t_freeze,
        'colored_by_group_score': mod_penalty or options.get('colored_by_group_score'),
        'contest': contest,
        'division': division,
        'contests_ids': contests_ids,
        'other_contests': other_contests,
        'contests_timelines': contests_timelines,
        'statistics': statistics,
        'my_statistics': my_statistics,
        'virtual_start': virtual_start,
        'virtual_start_statistics': virtual_start.statistics() if with_virtual_start else None,
        'with_virtual_start': with_virtual_start,
        'problems': problems,
        'hide_problems': hide_problems,
        'params': params,
        'settings_standings_fields': settings.STANDINGS_FIELDS_,
        'problem_user_solution_size_limit': settings.PROBLEM_USER_SOLUTION_SIZE_LIMIT,
        'fields': fields,
        'fields_types': fields_types,
        'hidden_fields': hidden_fields,
        'divisions_order': divisions_order,
        'has_country': has_country,
        'per_page': per_page,
        'per_page_more': per_page_more,
        'paginate_on_scroll': paginate_on_scroll,
        'force_both_scroll': force_both_scroll,
        'with_row_num': with_row_num,
        'merge_problems': merge_problems,
        'default_rowspan': mark_safe(' rowspan="2"') if merge_problems else '',
        'fields_to_select': fields_to_select,
        'truncatechars_name_problem': 10 * (2 if merge_problems else 1),
        'with_detail': with_detail,
        'with_solution': with_solution,
        'with_autoreload': with_autoreload,
        'groupby': groupby,
        'pie_limit_rows_groupby': 50,
        'labels_groupby': labels_groupby,
        'num_rows_groupby': num_rows_groupby,
        'map_colors_groupby': map_colors_groupby,
        'advance': contest.info.get('advance'),
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'with_neighbors': request.GET.get('neighbors') == 'on',
        'without_neighbors_aligment': not inner_scroll or 'safari' in request.user_agent.browser.family.lower(),
        'with_table_inner_scroll': inner_scroll and (not groupby or groupby == 'none') and not is_charts,
        'enable_timeline': enable_timeline,
        'contest_timeline': contest_timeline,
        'timeline': timeline,
        'timeline_durations': [
            ('100', '100 ms'),
            ('500', '500 ms'),
            ('1000', '1 sec'),
            ('2000', '2 sec'),
            ('4000', '4 sec'),
        ],
        'timeline_steps': [
            ('0.001', '0.1%'),
            ('0.005', '0.5%'),
            ('0.01', '1%'),
            ('0.05', '5%'),
            ('0.1', '10%'),
            ('0.2', '20%'),
        ],
        'timeline_delays': [
            ('500', '500 ms'),
            ('1000', '1 sec'),
            ('2000', '2 sec'),
            ('4000', '4 sec'),
            ('10000', '10 sec'),
        ],
        'timeline_freeze': [
            ('0', '0%'),
            ('0.2', '20%'),
            ('01:00:00', '1h'),
            ('0.5', '50%'),
            ('1.0', '100%'),
        ],
        'timeline_follow': [
            ('1', '1 sec'),
            ('10', '10 sec'),
            ('60', '1 min'),
            ('300', '5 min'),
            ('0', 'disable'),
        ],
        'groupby_data': statistics,
        'groupby_fields': fields,
    })

    context.update(n_highlight_context)

    if extra_context is not None:
        context.update(extra_context)

    if groupby == 'none' and is_charts:
        standings_charts(request, context)
        context['disable_switches'] = True
        if 'field' in fields_to_select:
            fields_to_select['field']['disabled'] = True

    return render(request, template, context)


@ratelimit(key='user', rate='20/m')
def solutions(request, sid, problem_key):
    is_modal = request.is_ajax()
    if not request.user.is_authenticated:
        if is_modal:
            return HttpResponseForbidden()
        return redirect_login(request)
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
        resource = statistic.contest.resource
        if stat.get('external_solution') or resource.info.get('standings', {}).get('external_solution'):
            try:
                source_code = resource.plugin.Statistic.get_source_code(statistic.contest, stat)
                stat.update(source_code)
            except NotImplementedError:
                return HttpResponseBadRequest('Not implemented')
            except (ExceptionParseStandings, FailOnGetResponse):
                return HttpResponseNotFound('Unable to obtain a solution')
            except ProxyLimitReached:
                return HttpResponseNotFound('Proxy limit reached')
        elif not stat.get('url'):
            return HttpResponseNotFound()

    return render(
        request,
        'solution-source.html' if is_modal else 'solution.html',
        {
            'is_modal': is_modal,
            'statistic': statistic,
            'account': statistic.account,
            'contest': statistic.contest,
            'problem': problem,
            'stat': stat,
            'fields': ['time', 'status', 'language'],
        })


@ratelimit(key='user', rate='20/m')
def score_history(request, statistic_id):
    is_modal = request.is_ajax()
    qs = Statistics.objects.select_related('account__resource', 'contest')
    qs = qs.filter(addition___score_history__isnull=False)
    statistic = get_object_or_404(qs, pk=statistic_id)

    score_history = statistic.addition['_score_history']
    resource = statistic.account.resource
    resource_score_history = get_item(resource, 'info.ratings.score_history', {})
    vertical_lines = []
    for hist in score_history:
        hist['date'] = arrow.get(hist['timestamp']).isoformat()
        hist['timestamp'] *= 1000
        if hist.get('updated'):
            vertical_lines.append(hist['timestamp'])
    base_chart = {
        'data': score_history,
        'vertical_lines': vertical_lines,
    }
    if resource_stages := resource_score_history.get('stages'):
        field = resource_stages['field']
        prev = score_history[0][field]
        strips = [{'name': prev, 'start': score_history[0]['timestamp']}]
        for hist in score_history[1:]:
            stage = hist[field]
            if stage != prev:
                strips[-1]['end'] = hist['timestamp']
                strips.append({'name': stage, 'start': hist['timestamp']})
            prev = stage
        strips[-1]['end'] = score_history[-1]['timestamp']
        if resource_colors := resource_stages.get('colors'):
            for strip in strips:
                strip['color'] = resource_colors.get(strip['name'])
        base_chart['strips'] = strips

        field_values = request.GET.getlist(field)
        for strip in strips:
            if strip['name'] in field_values:
                if 'x_min' not in base_chart:
                    base_chart['x_min'] = strip['start']
                base_chart['x_max'] = strip['end']

    template_name = 'score-history-modal.html' if is_modal else 'score-history.html'
    context = {
        'is_modal': is_modal,
        'charts': resource_score_history['charts'],
        'base_chart': base_chart,
        'statistic': statistic,
        'account': statistic.account,
        'contest': statistic.contest,
        'resource': resource,
    }
    return render(request, template_name, context)


@ratelimit(key='user', rate='5/m')
def score_histories(request, statistic_ids):
    statistic_ids = statistic_ids.split(',')
    is_modal = request.is_ajax()
    qs = Statistics.objects.select_related('account__resource', 'contest')
    qs = qs.filter(addition___score_history__isnull=False)
    statistics = qs.filter(pk__in=statistic_ids)

    statistic = statistics.first()
    if not statistic:
        return HttpResponseNotFound()
    contest = statistic.contest
    resource = statistic.account.resource
    resource_score_history = get_item(resource, 'info.ratings.score_history', {})

    order = contest.get_statistics_order()
    statistics = statistics.order_by(*order)
    statistics = statistics[:10]

    field_values = None
    if resource_stages := resource_score_history.get('stages'):
        field = resource_stages['field']
        field_values = request.GET.getlist(field)

    base_chart = {'datas': {}, 'fields': []}
    for statistic in statistics:
        name = statistic.account.short_display(resource=resource)
        if statistic.place:
            name = f"{statistic.place}. {name}"
        score_history = statistic.addition['_score_history']
        for hist in score_history:
            hist['date'] = arrow.get(hist['timestamp']).isoformat()
            hist['timestamp'] *= 1000
        if field_values:
            score_history = [hist for hist in score_history if hist[field] in field_values]
        base_chart['datas'][name] = score_history
        base_chart['fields'].append(name)

    template_name = 'score-history-modal.html' if is_modal else 'score-history.html'
    context = {
        'is_modal': is_modal,
        'charts': resource_score_history['charts'],
        'base_chart': base_chart,
        'resource': resource,
        'contest': contest,
        'statistics': statistics,
    }
    return render(request, template_name, context)


@login_required
@xframe_options_exempt
def standings_action(request):
    user = request.user
    message = None
    status, error = 200, None
    try:
        action = request.POST['action']
        if action == 'reset_contest_statistic_timing':
            contest_id = request.POST['cid']
            contest = Contest.objects.get(pk=contest_id)
            if has_update_statistics_permission(user, contest):
                message = f'Reset statistic timing for {contest}'
                contest.statistic_timing = None
                contest.save()
            else:
                status, error = 403, 'Permission denied'
        else:
            status, error = 400, 'Unknown action'
    except Exception:
        status, error = 500, 'Internal error'
    if error is not None:
        ret = {'status': 'error', 'message': error}
    else:
        ret = {'status': 'success', 'message': message}
    return JsonResponse(ret, status=status)


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

    resources = request.get_resources()
    if resources:
        base_filter &= Q(contest__resource__in=resources)

    filters = []
    urls = []
    display_names = []
    new_query = []
    redirect_new_query = False
    for idx, whos in enumerate(opponents):
        filt = Q()
        us = []
        ds = []

        n_accounts = 0
        for who in whos:
            n_accounts += ':' in who

        new_whos = []
        for who in whos:
            url = None
            display_name = who
            if ':' in who:
                host, key = who.split(':', 1)
                resource_q = Q(resource__host=host) | Q(resource__short_host=host)
                account = Account.objects.filter(resource_q, key=key).first()
                if not account:
                    renaming = AccountRenaming.objects.filter(resource_q, old_key=key).first()
                    if renaming:
                        account = Account.objects.filter(resource_q, key=renaming.new_key).first()
                    if account:
                        request.logger.warning(f'Replace {who} account to {account.key}')
                        redirect_new_query = True
                if not account:
                    request.logger.warning(f'Not found account {who}')
                else:
                    filt |= Q(account=account)
                    url = reverse('coder:account', kwargs={'key': account.key, 'host': account.resource.host})
                    new_whos.append(f'{host}:{account.key}')
                    display_name = f'{host}:'
                    if get_item(account.resource.info, 'standings.name_instead_key'):
                        display_name += account.name or account.key
                    else:
                        display_name += account.key
            else:
                coder = Coder.objects.filter(username=who).first()
                if not coder:
                    request.logger.warning(f'Not found coder {who}')
                else:
                    new_whos.append(who)
                    if n_accounts == 0:
                        filt |= Q(account__coders=coder)
                    else:
                        accounts = list(coder.account_set.all())
                        filt |= Q(account__in=accounts)
                    url = reverse('coder:profile', args=[coder.username])
                    display_name = coder.display_name
            ds.append(display_name)
            us.append(url)
        if not filt:
            filt = Q(pk=-1)
        display_names.append(ds)
        urls.append(us)
        filters.append(base_filter & filt)
        if new_whos:
            new_query.append(','.join(new_whos))

    if redirect_new_query and len(new_query) > 1:
        new_query = '/vs/'.join(new_query)
        url = reverse('ranking:versus', args=(new_query,))
        request.logger.info('Redirect to fixed versus url')
        raise RedirectException(redirect(url))

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
        'display_names': display_names,
        'urls': urls,
        'filters': filters,
        'contests_ids': contests_ids,
        'medal_contests_ids': medal_contests_ids,
    }


def versus(request, query):

    if request.GET.get('coder'):
        coder = get_object_or_404(Coder, pk=request.GET.get('coder'))
        return allowed_redirect(f'{request.path}vs/{coder.username}')

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
    contests = Contest.significant.filter(pk__in=versus_data['contests_ids']).order_by('-end_time', '-id')
    contests = contests.select_related('resource')

    search = request.GET.get('search')
    if search is not None:
        with_medal = False

        def set_medal(v):
            nonlocal with_medal
            with_medal = True
            return True

        contests_filter = get_iregex_filter(search,
                                            'title', 'host', 'resource__host',
                                            mapping={
                                                'contest': {'fields': ['title__iregex']},
                                                'resource': {'fields': ['host__iregex']},
                                                'slug': {'fields': ['slug']},
                                                'writer': {'fields': ['info__writers__contains']},
                                                'medal': {'fields': ['with_medals'], 'func': set_medal},
                                            },
                                            logger=request.logger)
        if with_medal:
            contests_filter |= Q(pk__in=versus_data['medal_contests_ids'])
        contests = contests.filter(contests_filter)

    medal = request.GET.get('medal')
    if medal:
        contests_filter = Q(with_medals=True)
        contests_filter |= Q(pk__in=versus_data['medal_contests_ids'])
        if medal == 'no':
            contests_filter = ~contests_filter
        contests = contests.filter(contests_filter)

    daterange = request.GET.get('daterange')
    if daterange:
        date_from, date_to = [arrow.get(x).datetime for x in daterange.split(' - ')]
        contests = contests.filter(start_time__gte=date_from, end_time__lte=date_to)

    resources = request.get_resources()
    if resources:
        params['resources'] = resources
        contests = contests.filter(resource__in=resources)

    # scoring by contests
    def cmp(a: tuple, b: tuple) -> bool:
        for x, y in zip(a, b):
            if x is not None and y is not None:
                return x < y
        return False

    scores = versus_data.setdefault('scores', {})
    for contest in reversed(contests):
        best = None
        indices = []
        for idx, info in enumerate(versus_data['infos']):
            stat = info['contests'][contest.pk]
            score = (stat.place_as_int, -stat.solving, stat.addition.get('penalty'))
            if best is None or cmp(score, best):
                best = score
                indices = [idx]
            elif not cmp(best, score):
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
                    'labels': [[','.join(whos)] for whos in versus_data['opponents']],
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

        values = list(values)
        if not values:
            continue

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
    if url and request.GET.get('redirect') in settings.YES_:
        return redirect(url)

    context = {
        'url': url,
        'opponents': opponents,
    }
    return render(request, 'make_versus.html', context)


@login_required
@page_template('virtual_start_paging.html')
@context_pagination()
def virtual_start(request, template='virtual_start.html'):
    coder = request.user.coder
    context = {}
    params = context.setdefault('params', {})
    resource = request.GET.get('resource')
    virtual_starts = VirtualStart.filter_by_content_type(Contest).filter(coder=coder).order_by('-start_time')
    if resource:
        resource = Resource.get_object(resource)
        params['resources'] = [resource]
        virtual_starts = virtual_starts.filter(contest__resource=resource)
    contest = request.GET.get('contest')
    if (contest == 'auto' or not contest) and resource:
        contest = resource.contest_set.filter(start_time__lt=timezone.now(), stage__isnull=True, invisible=False)
        contest = contest.annotate(disabled=VirtualStart.contests_filter(coder))
        contest = contest.order_by('-start_time').first()
        if contest and contest.disabled:
            contest = None
    elif contest and contest.isdigit():
        contest = Contest.objects.get(pk=contest)
        if resource and contest.resource_id != resource.id:
            return allowed_redirect(url_transform(request, contest=None, with_remove=True))
    elif contest:
        return HttpResponseBadRequest('Invalid contest')
    if contest:
        params['contests'] = [contest]

    action = request.GET.get('action')
    if action == 'start':
        return_redirect = allowed_redirect(url_transform(request, action=None, with_remove=True))
        if not contest:
            request.logger.error('No contest to start')
            return return_redirect
        if VirtualStart.objects.filter(coder=coder, contest=contest).exists():
            request.logger.error('Already started')
            return return_redirect
        VirtualStart.objects.create(coder=coder, entity=contest, start_time=timezone.now())
        context['open_url'] = contest.url
        params.pop('contests', None)

    context['virtual_starts'] = virtual_starts
    return template, context


@inject_contest()
def finalists(request, contest, template='finalists.html'):
    finalists = contest.finalist_set.order_by('created')
    finalist_resources = Resource.get(contest.finalists_info['resources'])
    resources = request.get_resources()
    resource_fields = finalist_resources
    force = 'force' in request.GET and request.user.is_staff
    update_delay = timedelta(days=1)
    with_update = timezone.now() < contest.start_time

    finalists = finalists.prefetch_related('finalistresourceinfo_set')

    achievement_statistics = Statistics.objects
    achievement_statistics = achievement_statistics.select_related('contest', 'resource', 'account')
    achievement_statistics = achievement_statistics.order_by('-contest__end_time', 'place_as_int')
    if resources:
        achievement_statistics = achievement_statistics.filter(resource__in=resources)
    finalists = finalists.prefetch_related(Prefetch('achievement_statistics', queryset=achievement_statistics))

    for finalist in finalists:
        accounts = finalist.accounts.all()
        last_modified = max(a.modified for a in accounts)

        accounts_filter = finalist.accounts.filter(coders=OuterRef('pk'))
        coders = Coder.objects.annotate(has_finalist_account=SubqueryExists(accounts_filter))
        coders = coders.filter(has_finalist_account=True)

        accounts_filter = Q(pk__in={a.pk for a in accounts})
        accounts_filter |= Q(coders__in=coders)

        resource_infos = {}
        for resource_info in finalist.finalistresourceinfo_set.all():
            resource_infos[resource_info.resource_id] = resource_info

        for resource in resource_fields:
            if resource.id not in resource_infos:
                resource_info, _ = FinalistResourceInfo.objects.get_or_create(finalist=finalist, resource=resource)
                resource_infos[resource.id] = resource_info
            else:
                resource_info = resource_infos[resource.id]

            if not with_update or resource_info.updated and last_modified < resource_info.updated + update_delay:
                continue

            rating_accounts = resource.account_set.filter(rating__isnull=False)
            rating_accounts = rating_accounts.filter(accounts_filter)
            ratings_data = rating_accounts.order_by('-rating').values('rating', 'key')
            if not ratings_data:
                continue

            rating = round(get_rating([r['rating'] for r in ratings_data]))
            if len(ratings_data) > 1:
                rating_infos = []
                for rating_data in ratings_data:
                    ratings = [r['rating'] for r in ratings_data if r['key'] != rating_data['key']]
                    rating_infos.append({'delta': rating - round(get_rating(ratings)), **rating_data})
            else:
                rating_infos = [dict(r) for r in ratings_data]

            resource_info.ratings = rating_infos
            resource_info.rating = rating
            resource_info.updated = timezone.now()
            resource_info.save()
        setattr(finalist, 'resource_infos', resource_infos)

        n_contests = [a.n_contests for a in accounts] + [c.n_contests for c in coders]
        n_contests = tuple(sorted(n_contests))
        achievement_hash = hashlib.md5(str(n_contests).encode()).hexdigest()
        if force or with_update and finalist.achievement_hash != achievement_hash:
            account_filter = Q(account__coders__in=coders) | Q(account__in=accounts)
            statistics = Statistics.objects.filter(account_filter)
            statistics = statistics.filter(medal__isnull=False)
            statistics = statistics.filter(contest__series__isnull=False, contest__end_time__lt=contest.start_time)
            statistics = statistics.order_by('-contest__end_time', 'place_as_int')
            finalist.achievement_statistics.set(statistics)
            finalist.achievement_hash = achievement_hash
            finalist.achievement_updated = timezone.now()
            finalist.save(update_fields=['achievement_hash', 'achievement_updated'])

    ach_max_date, ach_min_date = None, None
    for finalist in finalists:
        for statistic in finalist.achievement_statistics.all():
            ach_max_date = max_with_none(ach_max_date, statistic.contest.end_time)
            ach_min_date = min_with_none(ach_min_date, statistic.contest.end_time)

    context = {
        'navbar_admin_model': Finalist,
        'contest': contest,
        'has_name': contest.finalists_info.get('has_name'),
        'finalists': finalists,
        'finalist_resources': finalist_resources,
        'resource_fields': resource_fields,
        'ach_max_date': ach_max_date,
        'ach_min_date': ach_min_date,
        'params': {
            'resources': resources,
        },
    }
    return render(request, template, context)
