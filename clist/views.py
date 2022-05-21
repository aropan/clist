import re
from datetime import timedelta
from queue import SimpleQueue
from urllib.parse import parse_qs, urlparse

import arrow
import pytz
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.core.management.commands import dumpdata
from django.db.models import Avg, Count, F, FloatField, IntegerField, Max, Min, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Cast, Ln
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from el_pagination.decorators import page_template, page_templates
from sql_util.utils import Exists, SubqueryMin

from clist.models import Banner, Contest, Problem, ProblemTag, Resource
from clist.templatetags.extras import (as_number, canonize, get_problem_key, get_problem_name, get_problem_short,
                                       get_timezone_offset, get_timezones, rating_from_probability, slug)
from notification.management.commands import sendout_tasks
from pyclist.decorators import context_pagination
from ranking.models import Account, Rating, Statistics
from true_coders.models import Coder, Filter, Party
from utils.chart import make_bins, make_chart
from utils.json_field import JSONF
from utils.regex import get_iregex_filter, verify_regex


def get_timeformat(request):
    if "time_format" in request.GET:
        return request.GET["time_format"]
    ret = settings.TIME_FORMAT_
    if request.user.is_authenticated and hasattr(request.user, "coder"):
        ret = request.user.coder.settings.get("time_format", ret)
    return ret


def get_add_to_calendar(request):
    ret = settings.ADD_TO_CALENDAR_
    if request.user.is_authenticated and hasattr(request.user, "coder"):
        ret = request.user.coder.settings.get("add_to_calendar", ret)
    return settings.ACE_CALENDARS_[ret]['id']


def get_timezone(request):
    tz = request.GET.get("timezone", None)
    if tz:
        result = None
        try:
            pytz.timezone(tz)
            result = tz
        except Exception:
            if tz.startswith(" "):
                tz = tz.replace(" ", "+")
            for tzdata in get_timezones():
                if str(tzdata["offset"]) == tz or tzdata["repr"] == tz:
                    result = tzdata["name"]
                    break

        if result:
            if "update" in request.GET:
                if request.user.is_authenticated:
                    request.user.coder.timezone = result
                    request.user.coder.save()
                else:
                    request.session["timezone"] = result
                return
            return result

    if request.user.is_authenticated and hasattr(request.user, "coder"):
        return request.user.coder.timezone
    return request.session.get("timezone", settings.DEFAULT_TIME_ZONE_)


def get_view_contests(request, coder):
    user_contest_filter = Q()
    group_list = settings.GROUP_LIST_

    if coder:
        categories = request.GET.getlist('filter', ['list'])
        user_contest_filter = coder.get_contest_filter(categories)
        group_list = bool(coder.settings.get("group_in_list", group_list))
    else:
        categories = request.GET.getlist('filter')
        if categories:
            user_contest_filter = Coder.get_contest_filter(None, categories)

    group = request.GET.get('group')
    if group is not None:
        group_list = group and group.lower() in settings.YES_

    base_contests = Contest.visible.filter(user_contest_filter)
    if request.user.has_perm('reset_contest_statistic_timing'):
        base_contests = base_contests.select_related('timing')

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        base_contests = base_contests.filter(resource_id__in=resources)

    now = timezone.now()
    result = []
    status = request.GET.get('status')
    for group, query, order in (
        ("running", Q(start_time__lte=now, end_time__gte=now), "end_time"),
        ("coming", Q(start_time__gt=now), "start_time"),
    ):
        if status and group != status:
            continue
        group_by_resource = {}
        contests = base_contests.filter(query).order_by(order, 'title')
        contests = contests.select_related('resource')
        contests = contests.annotate(has_statistics=Exists('statistics'))
        for contest in contests:
            contest.state = group
            if group_list:
                group_by_resource.setdefault(contest.resource.id, []).append(contest)

        if group_list:
            for contest in contests:
                rid = contest.resource.id
                if rid in group_by_resource:
                    contest.group_size = len(group_by_resource[rid]) - 1
                    result.append(contest)
                    for c in group_by_resource[rid][1:]:
                        c.sub_contest = True
                        result.append(c)
                    del group_by_resource[rid]
        else:
            result.extend(contests)
    return result


@require_POST
def get_events(request):
    coder = request.user.coder if request.user.is_authenticated else None

    categories = request.POST.getlist('categories')
    ignore_filters = request.POST.getlist('ignore_filters')
    resources = [r for r in request.POST.getlist('resource') if r]
    status = request.POST.get('status')
    has_filter = False
    now = timezone.now()

    referer = request.META.get('HTTP_REFERER')
    if referer:
        parsed = urlparse(referer)
        query_dict = parse_qs(parsed.query)

        as_coder = query_dict.get('as_coder')
        if as_coder and request.user.has_perm('as_coder'):
            coder = Coder.objects.get(user__username=as_coder[0])

        has_filter = 'filter' in query_dict
        categories = query_dict.get('filter', categories)

    tzname = get_timezone(request)
    offset = get_timezone_offset(tzname)

    query = Q()
    if resources:
        query = Q(resource_id__in=resources)
    elif coder:
        query = coder.get_contest_filter(categories, ignore_filters)
    elif has_filter:
        query = Coder.get_contest_filter(None, categories, ignore_filters)

    if not coder or coder.settings.get('calendar_filter_long', True):
        if categories == ['calendar'] and '0' not in ignore_filters:
            query &= Q(duration_in_secs__lt=timedelta(days=1).total_seconds())

    past_action = settings.PAST_CALENDAR_DEFAULT_ACTION_
    if coder:
        past_action = coder.settings.get('past_action_in_calendar', past_action)

    start_time = arrow.get(request.POST.get('start', now)).datetime
    end_time = arrow.get(request.POST.get('end', now + timedelta(days=31))).datetime
    query = query & Q(end_time__gte=start_time) & Q(start_time__lte=end_time)

    search_query = request.POST.get('search_query', None)
    if search_query:
        search_query_re = verify_regex(search_query)
        query &= Q(host__iregex=search_query_re) | Q(title__iregex=search_query_re)

    party_slug = request.POST.get('party')
    if party_slug:
        party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
        query = Q(rating__party=party) & query

    contests = Contest.objects if party_slug else Contest.visible
    contests = contests.select_related('resource')
    contests = contests.annotate(has_statistics=Exists('statistics'))
    contests = contests.order_by('start_time', 'title')

    if past_action == 'hide':
        contests = contests.filter(end_time__gte=now)
    elif 'day' in past_action:
        threshold = now - timedelta(days=1) + timedelta(minutes=offset)
        start_day = threshold.replace(hour=0, minute=0, second=0, microsecond=0)
        contests = contests.filter(end_time__gte=start_day)
        past_action = past_action.split('-')[0]

    if status == 'coming':
        contests = contests.filter(start_time__gt=now)
    elif status == 'running':
        contests = contests.filter(start_time__lte=now, end_time__gte=now)

    try:
        result = []
        for contest in contests.filter(query):
            color = contest.resource.color
            if past_action not in ['show', 'hide'] and contest.end_time < now:
                color = contest.resource.info.get('get_events', {}).get('colors', {}).get(past_action, color)

            c = {
                'id': contest.pk,
                'title': contest.title,
                'host': contest.host,
                'url': (
                    reverse('ranking:standings', args=(slug(contest.title), contest.pk))
                    if contest.has_statistics else
                    (contest.standings_url if contest.standings_url and contest.end_time < now else contest.url)
                ),
                'start': (contest.start_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'end': (contest.end_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'countdown': contest.next_time_to(now),
                'hr_duration': contest.hr_duration,
                'color': color,
                'icon': contest.resource.icon,
            }
            result.append(c)
    except Exception as e:
        return JsonResponse({'message': f'query = `{search_query}`, error = {e}'}, safe=False, status=400)
    return JsonResponse(result, safe=False)


@login_required
def send_event_notification(request):
    method = request.POST['method']
    contest_id = request.POST['contest_id']
    message = request.POST['message']

    coder = request.user.coder

    sendout_tasks.Command().send_message(
        coder=coder,
        method=method,
        data={'contests': [int(contest_id)]},
        message=message.strip() + '\n',
    )

    return HttpResponse('ok')


def main(request, party=None):
    viewmode = settings.VIEWMODE_
    open_new_tab = settings.OPEN_NEW_TAB_
    hide_contest = settings.HIDE_CONTEST_
    share_to_category = None

    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        viewmode = coder.settings.get("view_mode", viewmode)
        hide_contest = coder.settings.get("hide_contest", hide_contest)
        open_new_tab = coder.settings.get("open_new_tab", open_new_tab)
        share_to_category = coder.settings.get("share_to_category", share_to_category)
    else:
        coder = None
    viewmode = request.GET.get("view", viewmode)
    hide_contest = request.GET.get("hide_contest", hide_contest)

    hide_contest = int(str(hide_contest).lower() in settings.YES_)

    time_format = get_timeformat(request)

    action = request.GET.get("action")
    if action is not None:
        if request.as_coder:
            return HttpResponseBadRequest("forbidden")
        if action == "party-contest-toggle" and request.user.is_authenticated:
            party = get_object_or_404(Party.objects.for_user(request.user), slug=request.GET.get("party"), author=coder)
            contest = get_object_or_404(Contest, pk=request.GET.get("pk"))
            rating, created = Rating.objects.get_or_create(contest=contest, party=party)
            if not created:
                rating.delete()
            return HttpResponse("ok")
        if action == "hide-contest-toggle":
            contest = get_object_or_404(Contest, pk=request.GET.get("pk"))
            filt, created = Filter.objects.get_or_create(coder=coder, contest=contest, to_show=False)
            if not created:
                filt.delete()
                return HttpResponse("deleted")
            return HttpResponse("created")
        return HttpResponseBadRequest("fail")

    has_tz = request.user.is_authenticated or "timezone" in request.session
    tzname = get_timezone(request)
    if tzname is None:
        return HttpResponse("accepted" if has_tz else "reload")

    if coder:
        ignore_filters = coder.ordered_filter_set.filter(categories__contains=['calendar'])
        ignore_filters = ignore_filters.filter(name__isnull=False).exclude(name='')
        ignore_filters = list(ignore_filters.values('id', 'name'))
    else:
        ignore_filters = []

    if not coder or coder.settings.get('calendar_filter_long', True):
        ignore_filters = ignore_filters + [{'id': 0, 'name': 'Disabled fitler'}]

    context = {
        "ignore_filters": ignore_filters,
        "contests": get_view_contests(request, coder),
    }

    if isinstance(party, Party):
        context["party"] = {
            "id": party.id,
            "toggle_contest": 1,
            "has_permission_toggle": int(party.has_permission_toggle_contests(coder)),
            "contest_ids": party.rating_set.values_list('contest__id', flat=True),
        }

    now = timezone.now()
    banners = Banner.objects.filter(end_time__gt=now)
    if not settings.DEBUG:
        banners = banners.filter(enable=True)

    offset = get_timezone_offset(tzname)

    context.update({
        "offset": offset,
        "now": now,
        "viewmode": viewmode,
        "hide_contest": hide_contest,
        "share_to_category": share_to_category,
        "timezone": tzname,
        "time_format": time_format,
        "open_new_tab": open_new_tab,
        "add_to_calendar": get_add_to_calendar(request),
        "banners": banners,
    })

    return render(request, "main.html", context)


def update_coder_range_filter(coder, values, name):
    if not coder or not values:
        return
    range_filter = coder.settings.setdefault('range_filter', {}).setdefault(name, {})
    to_save = False
    for k, v in values.items():
        if v is not None and range_filter.get(k) != v:
            range_filter[k] = v
            to_save = True
    if to_save:
        coder.save()


def resources(request):
    resources = Resource.objects
    resources = resources.select_related('module')
    resources = resources.annotate(has_rating_i=Cast('has_rating_history', IntegerField()))
    resources = resources.annotate(has_rating_f=Cast('has_rating_i', FloatField()))
    resources = resources.annotate(priority=Ln(F('n_contests') + 1) + Ln(F('n_accounts') + 1) + 2 * F('has_rating_f'))
    resources = resources.order_by('-priority')
    return render(request, 'resources.html', {'resources': resources})


def resource_problem_rating_chart(resource):
    step = resource.rating_step()
    problems = resource.problem_set.all()
    problem_rating_chart = make_chart(problems, 'rating', n_bins=20, cast='int', step=step)
    if not problem_rating_chart:
        return

    data = problem_rating_chart['data']
    idx = 0
    for rating in resource.ratings:
        while idx < len(data) and int(data[idx]['bin']) <= rating['high']:
            data[idx]['bgcolor'] = rating['hex_rgb']
            if idx + 1 < len(data):
                data[idx]['title'] = f"{data[idx]['bin']}..{int(data[idx + 1]['bin']) - 1}"
            else:
                data[idx]['title'] = data[idx]['bin']
            if 'name' in rating:
                data[idx]['subtitle'] = rating['name']
            idx += 1

    problem_rating_chart['mode'] = 'index'
    problem_rating_chart['hover_mode'] = 'index'
    problem_rating_chart['border_color'] = '#fff'
    problem_rating_chart['bar_percentage'] = 1.0
    problem_rating_chart['category_percentage'] = 1.0
    return problem_rating_chart


@page_templates((
    ('resource_country_paging.html', 'country_page'),
    ('resource_last_activity_paging.html', 'last_activity_page'),
    ('resource_top_paging.html', 'top_page'),
    ('resource_most_participated_paging.html', 'most_participated_page'),
    ('resource_most_writer_paging.html', 'most_writer_page'),
    ('resource_contests.html', 'past_page'),
    ('resource_contests.html', 'coming_page'),
    ('resource_contests.html', 'running_page'),
    ('resource_problems_paging.html', 'problems_page'),
))
def resource(request, host, template='resource.html', extra_context=None):
    now = timezone.now()
    resource = get_object_or_404(Resource, host=host)

    if request.user.is_authenticated:
        coder = request.user.coder
        coder_account = coder.account_set.filter(resource=resource, rating__isnull=False).first()
        coder_account_ids = set(coder.account_set.filter(resource=resource).values_list('id', flat=True))
        show_coder_account_rating = True
    else:
        coder = None
        coder_account = None
        coder_account_ids = set()
        show_coder_account_rating = False

    params = {}

    contests = resource.contest_set.annotate(has_statistics=Exists('statistics'))

    accounts = Account.objects.filter(resource=resource)

    has_country = accounts.filter(country__isnull=False).exists()
    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        params['countries'] = countries
        accounts = accounts.filter(country__in=countries)

    period = request.GET.get('period', 'all')
    params['period'] = period
    deltas_period = {
        'month': timedelta(days=30 * 1),
        'quarter': timedelta(days=30 * 3),
        'half': timedelta(days=30 * 6),
        'year': timedelta(days=30 * 12),
        'all': None,
    }
    periods = list(deltas_period.keys())
    delta_period = deltas_period.get(period, None)
    if delta_period:
        accounts = accounts.filter(last_activity__gte=now - delta_period)

    default_variables = resource.info.get('default_variables', {})
    range_filter_values = {}
    for field, operator in (
        ('rating_from', 'rating__gte'),
        ('rating_to', 'rating__lte'),
        ('n_participations_from', 'n_contests__gte'),
        ('n_participations_to', 'n_contests__lte'),
    ):
        value = as_number(request.GET.get(field), force=True)
        if value is not None:
            range_filter_values[field] = value
        else:
            value = default_variables.get(field)
        if value is not None:
            params[field] = value
            accounts = accounts.filter(**{operator: value})
    update_coder_range_filter(coder, range_filter_values, resource.host)

    countries = (accounts
                 .filter(country__isnull=False)
                 .values('country')
                 .annotate(count=Count('country'))
                 .order_by('-count', 'country'))

    min_rating = 0
    max_rating = 5000
    if resource.ratings:
        values = resource.account_set.aggregate(min_rating=Min('rating'), max_rating=Max('rating'))
        min_rating = values['min_rating']
        max_rating = values['max_rating']
        ratings = accounts.filter(rating__isnull=False)
        rating_field = 'rating'

        n_x_axis = resource.info.get('ratings', {}).get('chartjs', {}).get('n_x_axis')
        if n_x_axis:
            n_bins = n_x_axis
            step = None
        else:
            n_bins = 30
            step = resource.rating_step()

        coloring_field = resource.info.get('ratings', {}).get('chartjs', {}).get('coloring_field')
        if coloring_field:
            ratings = ratings.annotate(rank=Cast(JSONF(f'info__{coloring_field}'), IntegerField()))
            aggregations = {'coloring_field': Avg('rank')}
        else:
            aggregations = None

        rating_chart = make_chart(ratings, rating_field, n_bins=n_bins, step=step, aggregations=aggregations)

        if rating_chart:
            data = rating_chart['data']
            for idx, row in enumerate(data):
                row['rating'] = row.pop('bin')
                row['count'] = row.pop('value')

            idx = 0
            for row in data:
                if coloring_field:
                    if 'coloring_field' not in row or row['coloring_field'] is None:
                        row['info'] = resource.ratings[idx]
                        continue
                    val = row['coloring_field']
                else:
                    val = int(row['rating'])
                while val > resource.ratings[idx]['high']:
                    idx += 1
                while val < resource.ratings[idx]['low']:
                    idx -= 1
                row['info'] = resource.ratings[idx]
    else:
        rating_chart = None

    context = {
        'resource': resource,
        'coder': coder,
        'coder_accounts_ids': coder_account_ids,
        'accounts': resource.account_set.filter(coders__isnull=False).prefetch_related('coders').order_by('-modified'),
        'countries': countries,
        'rating': {
            'chart': rating_chart,
            'account': coder_account if show_coder_account_rating else None,
            'min': min_rating,
            'max': max_rating,
        },
        'contests': {
            'past': {
                'contests': contests.filter(end_time__lt=now).order_by('-end_time'),
                'field': 'end_time',
                'url': reverse('ranking:standings_list') + f'?resource={resource.pk}',
            },
            'coming': {
                'contests': contests.filter(start_time__gt=now).order_by('start_time'),
                'field': 'start_time',
                'url': reverse('clist:main') + f'?resource={resource.pk}&view=list&group=no&status=coming',
            },
            'running': {
                'contests': contests.filter(start_time__lt=now, end_time__gt=now).order_by('end_time'),
                'field': 'time_left',
                'url': reverse('clist:main') + f'?resource={resource.pk}&view=list&group=no&status=running',
            },
        },
        'contest_key': None,
        'has_country': has_country,
        'periods': periods,
        'params': params,
        'first_per_page': 10,
        'per_page': 50,
        'last_activities': accounts.filter(last_activity__isnull=False).order_by('-last_activity', 'id'),
        'top': accounts.filter(rating__isnull=False).order_by('-rating', 'id'),
        'most_participated': accounts.order_by('-n_contests', 'id'),
        'most_writer': accounts.filter(n_writers__gt=0).order_by('-n_writers', 'id'),
        'problems': resource.problem_set.filter(url__isnull=False).order_by('-time', 'contest_id', 'index'),
    }

    if extra_context.get('page_template'):
        context.update(extra_context)
    elif resource.has_problem_rating:
        context['problem_rating_chart'] = resource_problem_rating_chart(resource)

    return render(request, template, context)


@permission_required('clist.view_resources_dump_data')
def resources_dumpdata(request):
    response = HttpResponse(content_type="application/json")
    dumpdata.Command(stdout=response).run_from_argv([
        'manage.py',
        'dumpdata',
        'clist.resource',
        'ranking.module',
        '--format', 'json'
    ])
    return response


def update_writers(contest, writers=None):
    if writers is not None:
        if canonize(writers) == canonize(contest.info.get('writers')):
            return
        contest.info['writers'] = writers
        contest.save()

    def get_re_writers(writers):
        ret = '|'.join([re.escape(w) for w in writers])
        ret = f'^({ret})$'
        return ret

    writers = contest.info.get('writers', [])
    if not writers:
        contest.writers.clear()
        return

    re_writers = get_re_writers(writers)
    for writer in contest.writers.filter(~Q(key__iregex=re_writers)):
        contest.writers.remove(writer)
    already_writers = set(contest.writers.filter(key__iregex=re_writers).values_list('key', flat=True))
    re_already_writers = re.compile(get_re_writers(already_writers))
    for writer in writers:
        if re_already_writers.match(writer):
            continue

        account = Account.objects.filter(resource=contest.resource, key__iexact=writer).order_by('-n_contests').first()
        if account is None:
            account, created = Account.objects.get_or_create(resource=contest.resource, key=writer)
        account.writer_set.add(contest)


def update_problems(contest, problems=None, force=False):
    if problems is not None and not force:
        if canonize(problems) == canonize(contest.info.get('problems')):
            return
    contest.info['problems'] = problems
    contest.save()

    if hasattr(contest, 'stage'):
        return

    contests_set = {contest.pk}
    contests_queue = SimpleQueue()
    contests_queue.put(contest)

    old_problem_ids = set(contest.problem_set.values_list('id', flat=True))
    added_problems = dict()

    while not contests_queue.empty():
        current_contest = contests_queue.get()

        problems = current_contest.info.get('problems')
        if 'division' in problems:
            problem_sets = problems['division'].items()
        else:
            problem_sets = [(None, problems)]

        for division, problem_set in problem_sets:
            last_group = None
            for index, problem_info in enumerate(problem_set, start=1):
                key = get_problem_key(problem_info)
                short = get_problem_short(problem_info)
                name = get_problem_name(problem_info)
                if last_group is not None and last_group == problem_info.get('group'):
                    continue
                last_group = problem_info.get('group')
                problem_contest = contest if 'code' not in problem_info else None

                added_problem = added_problems.get(key)
                if current_contest != contest and not added_problem:
                    continue

                if problem_info.get('_no_problem_url'):
                    url = getattr(added_problem, 'url', None) or problem_info.get('url')
                else:
                    url = problem_info.get('url') or getattr(added_problem, 'url', None)

                defaults = {
                    'index': index if getattr(added_problem, 'index', index) == index else None,
                    'short': short if getattr(added_problem, 'short', short) == short else None,
                    'name': name,
                    'divisions': getattr(added_problem, 'divisions', []) + ([division] if division else []),
                    'url': url,
                    'n_tries': problem_info.get('n_teams', 0) + getattr(added_problem, 'n_tries', 0),
                    'n_accepted': problem_info.get('n_accepted', 0) + getattr(added_problem, 'n_accepted', 0),
                    'n_partial': problem_info.get('n_partial', 0) + getattr(added_problem, 'n_partial', 0),
                    'n_hidden': problem_info.get('n_hidden', 0) + getattr(added_problem, 'n_hidden', 0),
                    'n_total': problem_info.get('n_total', 0) + getattr(added_problem, 'n_total', 0),
                    'time': max(contest.start_time, getattr(added_problem, 'time', contest.start_time)),
                }
                if getattr(added_problem, 'rating', None) is not None:
                    problem_info['rating'] = added_problem.rating
                elif 'rating' in problem_info:
                    defaults['rating'] = problem_info['rating']
                if 'visible' in problem_info:
                    defaults['visible'] = problem_info['visible']

                problem, created = Problem.objects.update_or_create(
                    contest=problem_contest,
                    resource=contest.resource,
                    key=key,
                    defaults=defaults,
                )
                problem.contests.add(contest)

                old_tags = set(problem.tags.all())
                if 'tags' in problem_info:
                    if '' in problem_info['tags']:
                        problem_info['tags'].remove('')
                        contest.save()

                    for name in problem_info['tags']:
                        tag, _ = ProblemTag.objects.get_or_create(name=name)
                        if tag in old_tags:
                            old_tags.discard(tag)
                        else:
                            problem.tags.add(tag)
                if not added_problem:
                    for tag in old_tags:
                        problem.tags.remove(tag)

                added_problems[key] = problem

                if problem.id in old_problem_ids:
                    old_problem_ids.remove(problem.id)

                for c in problem.contests.all():
                    if c.pk in contests_set:
                        continue
                    contests_set.add(c.pk)
                    contests_queue.put(c)
        current_contest.save()

    if old_problem_ids:
        for problem in Problem.objects.filter(id__in=old_problem_ids):
            problem.contests.remove(contest)
            if problem.contests.count() == 0:
                problem.delete()

    return True


@page_template('problems_paging.html')
@context_pagination()
def problems(request, template='problems.html'):
    problems = Problem.objects.all()
    problems = problems.select_related('resource')
    problems = problems.prefetch_related('contests')
    problems = problems.prefetch_related('tags')
    problems = problems.annotate(min_contest_id=SubqueryMin('contests__id'))
    problems = problems.order_by('-time', '-min_contest_id', 'rating', 'index', 'short')
    problems = problems.filter(visible=True)

    show_tags = True
    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        has_update_coder = not bool(request.as_coder)
        show_tags = coder.settings.get('show_tags', show_tags)
        statistics = Statistics.objects.filter(account__coders=coder)
        accounts = Account.objects.filter(coders=coder, rating__isnull=False, resource=OuterRef('resource'))
        accounts = accounts.order_by('rating').values('rating')[:1]
        problems = problems.annotate(account_rating=Subquery(accounts))
        problem_rating_accounts = (
            coder.account_set
            .filter(rating__isnull=False, resource__has_problem_rating=True)
            .select_related('resource')
        )
    else:
        coder = None
        has_update_coder = False
        statistics = Statistics.objects.none()
        problem_rating_accounts = []
    problems = problems.prefetch_related(Prefetch('contests__statistics_set', queryset=statistics))

    show_tags_value = str(request.GET.get('show_tags', '')).lower()
    if show_tags_value:
        show_tags = show_tags_value in settings.YES_

    search = request.GET.get('search')
    if search:
        cond, problems = get_iregex_filter(
            search,
            'name',
            logger=request.logger,
            mapping={
                'name': {'fields': ['name__iregex']},
                'contest': {'fields': ['contest__title__iregex'], 'exists': 'contests'},
                'resource': {'fields': ['resource__host__iregex']},
                'tag': {'fields': ['problemtag__name__iregex'], 'exists': 'tags'},
                'cid': {'fields': ['contest__pk'], 'exists': 'contests', 'func': lambda v: int(v)},
                'rid': {'fields': ['resource_id'], 'func': lambda v: int(v)},
                'pid': {'fields': ['id'], 'func': lambda v: int(v)},
                'n_accepted':  {'fields': ['n_accepted']},
                'n_partial':  {'fields': ['n_partial']},
                'n_hidden':  {'fields': ['n_hidden']},
                'n_total':  {'fields': ['n_total']},
            },
            queryset=problems,
        )
        problems = problems.filter(cond)

    range_filter_values = {}

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        problems = problems.filter(resource_id__in=resources)
        if coder:
            problem_rating_accounts = problem_rating_accounts.filter(resource__pk__in=resources)
        resources = list(Resource.objects.filter(pk__in=resources))

    luck_from = as_number(request.GET.get('luck_from'), force=True)
    luck_to = as_number(request.GET.get('luck_to'), force=True)
    if luck_from is not None or luck_to is not None:
        luck_filter = Q()
        for account in problem_rating_accounts:
            cond = Q(resource=account.resource)
            if luck_from is not None:
                range_filter_values['luck_from'] = luck_from
                rating_to = rating_from_probability(account.rating, luck_from / 100)
                cond &= Q(rating__lte=rating_to)
            if luck_to is not None:
                range_filter_values['luck_to'] = luck_to
                rating_from = rating_from_probability(account.rating, luck_to / 100)
                cond &= Q(rating__gte=rating_from)
            luck_filter |= cond
        if luck_filter:
            problems = problems.filter(luck_filter)

    rating_from = as_number(request.GET.get('rating_from'), force=True)
    rating_to = as_number(request.GET.get('rating_to'), force=True)
    if rating_from is not None or rating_to is not None:
        rating_filter = Q()
        if rating_from is not None:
            range_filter_values['rating_from'] = rating_from
            rating_filter &= Q(rating__gte=rating_from)
        if rating_to is not None:
            range_filter_values['rating_to'] = rating_to
            rating_filter &= Q(rating__lte=rating_to)
        problems = problems.filter(rating_filter)

    if has_update_coder:
        update_coder_range_filter(coder, range_filter_values, 'problems')

    tags = [r for r in request.GET.getlist('tag') if r]
    if tags:
        problems = problems.annotate(has_tag=Exists('tags', filter=Q(problemtag__pk__in=tags)))
        problems = problems.filter(has_tag=True)
        tags = list(ProblemTag.objects.filter(pk__in=tags))

    chart_select = {
        'values': [v for v in request.GET.getlist('chart') if v],
        'options': ['date', 'rating'] + (['luck'] if coder else []),
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
        'nofilter': True,
        'nomultiply': True,
    }
    chart_field = request.GET.get('chart')
    if chart_field == 'rating':
        resource = resources[0] if resources and len(resources) == 1 and resources[0].has_rating_history else None
        step = resource.rating_step() if resource else None
        chart = make_chart(problems, field='rating', step=step, logger=request.logger)
        if resource:
            for data in chart['data']:
                val = as_number(data['bin'], force=True)
                if val is None:
                    continue
                for rating in resource.ratings:
                    if rating['low'] <= val <= rating['high']:
                        data['bgcolor'] = rating['hex_rgb']
                        break
    elif chart_field == 'date':
        chart = make_chart(problems, field='time', logger=request.logger)
    elif chart_field == 'luck' and coder:
        luck_from = 0 if luck_from is None else luck_from
        luck_to = 100 if luck_to is None else luck_to
        bins = make_bins(float(luck_from), float(luck_to), n_bins=41)
        data = [{'bin': b, 'value': 0} for b in bins[:-1]]

        for account in problem_rating_accounts:
            ratings = [round(rating_from_probability(account.rating, b / 100)) for b in bins[::-1]]
            c = make_chart(problems.filter(resource=account.resource), field='rating', bins=ratings)
            if c is None:
                continue
            for row, d in zip(data, c['data'][::-1]):
                row['value'] += d['value']
        chart = {
            'field': 'luck',
            'data': data,
            'bins': bins,
        }
    else:
        chart = None

    context = {
        'problems': problems,
        'coder': coder,
        'show_tags': show_tags,
        'params': {
            'resources': resources,
            'tags': tags,
        },
        'chart_select': chart_select,
        'chart': chart,
    }

    return template, context
