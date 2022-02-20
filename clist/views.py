import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import arrow
import pytz
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.core.management.commands import dumpdata
from django.db.models import Avg, Count, F, FloatField, IntegerField, Max, Min, Q
from django.db.models.functions import Cast, Ln
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from el_pagination.decorators import page_template, page_templates
from sql_util.utils import Exists

from clist.models import Banner, Contest, Problem, ProblemTag, Resource
from clist.templatetags.extras import (canonize, get_problem_key, get_problem_name, get_problem_short,
                                       get_timezone_offset, get_timezones, slug)
from notification.management.commands import sendout_tasks
from pyclist.decorators import context_pagination
from ranking.models import Account, Rating
from true_coders.models import Coder, Filter, Party
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

    now = timezone.now()
    result = []
    for group, query, order in (
        ("running", Q(start_time__lte=now, end_time__gte=now), "end_time"),
        ("coming", Q(start_time__gt=now), "start_time"),
    ):
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
    if request.user.is_authenticated:
        coder = request.user.coder
    else:
        coder = None

    categories = request.POST.getlist('categories')
    ignore_filters = request.POST.getlist('ignore_filters')
    has_filter = False

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
    if coder:
        query = coder.get_contest_filter(categories, ignore_filters)
    elif has_filter:
        query = Coder.get_contest_filter(None, categories, ignore_filters)

    if not coder or coder.settings.get('calendar_filter_long', True):
        if categories == ['calendar'] and '0' not in ignore_filters:
            query &= Q(duration_in_secs__lt=timedelta(days=1).total_seconds())

    past_action = settings.PAST_CALENDAR_DEFAULT_ACTION_
    if coder:
        past_action = coder.settings.get('past_action_in_calendar', past_action)

    start_time = arrow.get(request.POST.get('start', timezone.now())).datetime
    end_time = arrow.get(request.POST.get('end', timezone.now() + timedelta(days=31))).datetime
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
        contests = contests.filter(end_time__gte=timezone.now())

    now = timezone.now()
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
        if request.GET.get('as_coder') and request.user.has_perm('as_coder'):
            coder = Coder.objects.get(user__username=request.GET['as_coder'])
        else:
            coder = request.user.coder
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


def resources(request):
    resources = Resource.objects
    resources = resources.select_related('module')
    resources = resources.annotate(has_rating_i=Cast('has_rating_history', IntegerField()))
    resources = resources.annotate(has_rating_f=Cast('has_rating_i', FloatField()))
    resources = resources.annotate(priority=Ln(F('n_contests') + 1) + Ln(F('n_accounts') + 1) + 2 * F('has_rating_f'))
    resources = resources.order_by('-priority')
    return render(request, 'resources.html', {'resources': resources})


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
    for field, operator in (
        ('min_rating', 'rating__gte'),
        ('max_rating', 'rating__lte'),
        ('min_n_participations', 'n_contests__gte'),
        ('max_n_participations', 'n_contests__lte'),
    ):
        value = request.GET.get(field, default_variables.get(field))
        if value:
            params[field] = value
        if field in params:
            accounts = accounts.filter(**{operator: params[field]})

    countries = accounts \
        .filter(country__isnull=False) \
        .values('country') \
        .annotate(count=Count('country')) \
        .order_by('-count', 'country')

    n_x_axis = resource.info.get('ratings', {}).get('chartjs', {}).get('n_x_axis')
    coloring_field = resource.info.get('ratings', {}).get('chartjs', {}).get('coloring_field')

    width = 50
    min_rating = params.get('min_rating')
    max_rating = params.get('max_rating')
    if n_x_axis or min_rating and max_rating and int(max_rating) - int(min_rating) <= 100:
        width = 1
    rating_field = 'rating50' if width == 50 else 'rating'

    ratings = accounts.filter(**{f'{rating_field}__isnull': False})

    if n_x_axis:
        rs = ratings.aggregate(max_rating=Max(rating_field), min_rating=Min(rating_field))
        if rs['max_rating'] is not None:
            width = max((rs['max_rating'] - rs['min_rating']) // n_x_axis, 1)
        else:
            width = 1
        ratings = ratings.annotate(ratingw=F(rating_field) / width)
        rating_field = 'ratingw'

    annotations = {'count': Count(rating_field)}
    if coloring_field:
        ratings = ratings.annotate(rank=Cast(KeyTextTransform(coloring_field, 'info'), IntegerField()))
        annotations['coloring_field'] = Avg('rank')

    ratings = ratings \
        .values(rating_field) \
        .annotate(**annotations) \
        .order_by(rating_field)

    ratings = list(ratings)

    labels = []
    data = []
    if ratings and resource.ratings:
        idx = 0
        for rating in ratings:
            low = rating[rating_field] * width
            high = low + width - 1

            val = rating.get('coloring_field', low)
            if val is None:
                continue
            while val > resource.ratings[idx]['high']:
                idx += 1
            while idx and val <= resource.ratings[idx - 1]['high']:
                idx -= 1

            data.append({
                'title': f'{low}..{high}',
                'rating': low,
                'count': rating['count'],
                'info': resource.ratings[idx],
            })
        min_rating = ratings[0][rating_field]
        max_rating = ratings[-1][rating_field]
        labels = list(range(min_rating * width, max_rating * width + 1, width))

    context = {
        'resource': resource,
        'coder': coder,
        'coder_accounts_ids': coder_account_ids,
        'accounts': resource.account_set.filter(coders__isnull=False).prefetch_related('coders').order_by('-modified'),
        'countries': countries,
        'rating': {
            'labels': labels,
            'data': data,
            'account': coder_account if show_coder_account_rating else None,
            'width': width,
        },
        'contests': {
            'past': {
                'contests': contests.filter(end_time__lt=now).order_by('-end_time'),
                'field': 'end_time',
            },
            'coming': {
                'contests': contests.filter(start_time__gt=now).order_by('start_time'),
                'field': 'start_time',
            },
            'running': {
                'contests': contests.filter(start_time__lt=now, end_time__gt=now).order_by('end_time'),
                'field': 'time_left',
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

    if extra_context is not None:
        context.update(extra_context)

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

    problems = contest.info.get('problems')
    if not problems or hasattr(contest, 'stage'):
        return
    if 'division' in problems:
        problem_sets = problems['division'].items()
    else:
        problem_sets = [(None, problems)]

    old_problem_ids = set(contest.problem_set.values_list('id', flat=True))
    added_problems = dict()
    for division, problem_set in problem_sets:
        last_group = None
        for index, problem_info in enumerate(problem_set, start=1):
            key = get_problem_key(problem_info)
            short = get_problem_short(problem_info)
            name = get_problem_name(problem_info)
            if short == name or short == key:
                short = None
            if last_group is not None and last_group == problem_info.get('group'):
                continue
            last_group = problem_info.get('group')

            added_problem = added_problems.get(key)

            defaults = {
                'index': index if not added_problem else None,
                'short': short,
                'name': name,
                'divisions': getattr(added_problem, 'divisions', []) + [division] if division else None,
                'url': problem_info.get('url'),
                'n_tries': problem_info.get('n_teams', 0) + getattr(added_problem, 'n_tries', 0),
                'n_accepted': problem_info.get('n_accepted', 0) + getattr(added_problem, 'n_accepted', 0),
                'time': contest.start_time,
            }
            if 'visible' in problem_info:
                defaults['visible'] = problem_info['visible']

            problem, created = Problem.objects.update_or_create(
                contest=contest,
                resource=contest.resource,
                key=key,
                defaults=defaults,
            )

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
            for tag in old_tags:
                problem.tags.remove(tag)

            added_problems[key] = problem

            if problem.id in old_problem_ids:
                old_problem_ids.remove(problem.id)

    if old_problem_ids:
        Problem.objects.filter(id__in=old_problem_ids).delete()


@page_template('problems_paging.html')
@context_pagination()
def problems(request, template='problems.html'):
    problems = Problem.objects.all()
    problems = problems.select_related('contest', 'resource')
    problems = problems.prefetch_related('tags')
    problems = problems.order_by('-time', 'contest_id', 'index')
    problems = problems.filter(contest__end_time__lt=timezone.now(), visible=True)

    search = request.GET.get('search')
    if search:
        cond, problems = get_iregex_filter(
            search,
            'name', 'contest__title', 'contest__host', 'contest__resource__host',
            logger=request.logger,
            mapping={
                'name': {'fields': ['name__iregex']},
                'contest': {'fields': ['contest__title__iregex']},
                'resource': {'fields': ['resource__host__iregex']},
                'tag': {'fields': ['problemtag__name__iregex'], 'exists': 'tags'},
                'cid': {'fields': ['contest_id'], 'func': lambda v: int(v)},
                'rid': {'fields': ['resource_id'], 'func': lambda v: int(v)},
                'pid': {'fields': ['id'], 'func': lambda v: int(v)},
            },
            queryset=problems,
        )
        problems = problems.filter(cond)

    resources = [r for r in request.GET.getlist('resource') if r]
    if resources:
        problems = problems.filter(contest__resource_id__in=resources)
        resources = list(Resource.objects.filter(pk__in=resources))

    tags = [r for r in request.GET.getlist('tag') if r]
    if tags:
        problems = problems.annotate(has_tag=Exists('tags', filter=Q(problemtag__pk__in=tags)))
        problems = problems.filter(has_tag=True)
        tags = list(ProblemTag.objects.filter(pk__in=tags))

    context = {
        'problems': problems,
        'params': {
            'resources': resources,
            'tags': tags,
        },
    }

    return template, context
