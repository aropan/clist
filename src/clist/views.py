import re
from collections import OrderedDict
from copy import deepcopy
from datetime import timedelta
from queue import SimpleQueue
from urllib.parse import parse_qs, urlparse

import arrow
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.core.management.commands import dumpdata
from django.db import transaction
from django.db.models import Avg, Count, F, FloatField, IntegerField, Max, Min, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Cast
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_super_deduper.merge import MergedModelInstance
from el_pagination.decorators import QS_KEY, page_templates
from sql_util.utils import Exists, SubqueryCount, SubqueryMin

from clist.models import Banner, Contest, Problem, ProblemTag, ProblemVerdict, PromoLink, Promotion, Resource
from clist.templatetags.extras import (as_number, canonize, get_problem_key, get_problem_name, get_problem_short,
                                       get_timezone_offset, rating_from_probability, win_probability)
from favorites.models import Activity
from favorites.templatetags.favorites_extras import activity_icon
from notification.management.commands import sendout_tasks
from pyclist.decorators import context_pagination
from ranking.models import Account, CountryAccount, Rating, Statistics
from true_coders.models import Coder, CoderList, CoderProblem, Filter, Party
from utils.chart import make_bins, make_chart
from utils.json_field import JSONF
from utils.regex import get_iregex_filter, verify_regex
from utils.timetools import get_timeformat, get_timezone


def get_add_to_calendar(request):
    ret = settings.ADD_TO_CALENDAR_
    if request.user.is_authenticated and hasattr(request.user, "coder"):
        ret = request.user.coder.settings.get("add_to_calendar", ret)
    return settings.ACE_CALENDARS_[ret]['id']


def get_group_list(request):
    ret = settings.GROUP_LIST_
    coder = request.user.coder if request.user.is_authenticated else None
    if coder:
        ret = bool(coder.settings.get("group_in_list", ret))

    group = request.GET.get('group')
    if group is not None:
        ret = group and group.lower() in settings.YES_

    return ret


def get_view_contests(request, coder):
    user_contest_filter = Q()
    group_list = get_group_list(request)

    if coder:
        categories = request.GET.getlist('filter', ['list'])
        user_contest_filter = coder.get_contest_filter(categories)
    else:
        categories = request.GET.getlist('filter')
        if categories:
            user_contest_filter = Coder.get_contest_filter(None, categories)

    base_contests = Contest.visible.annotate_favorite(coder)
    base_contests = base_contests.filter(user_contest_filter)

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
        coder = request.as_coder or coder
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

    favorite_value = request.POST.get('favorite')
    if favorite_value == 'on':
        query &= Q(is_favorite=True)
    elif favorite_value == 'off':
        query &= Q(is_favorite=False)

    party_slug = request.POST.get('party')
    if party_slug:
        party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
        query = Q(ratings__party=party) & query

    contests = Contest.objects if party_slug else Contest.visible
    contests = contests.annotate_favorite(coder)
    contests = contests.select_related('resource')
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
                'url': contest.actual_url,
                'start': (contest.start_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'end': (contest.end_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'countdown': contest.next_time_to(now),
                'hr_duration': contest.hr_duration,
                'color': color,
                'icon': contest.resource.icon,
                'allDay': contest.full_duration >= timedelta(days=1),
            }
            if coder:
                c['favorite'] = contest.is_favorite
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
        ignore_filters = coder.ordered_filter_set.filter(categories__contains=['calendar'], enabled=True)
        ignore_filters = ignore_filters.filter(name__isnull=False).exclude(name='')
        ignore_filters = list(ignore_filters.values('id', 'name'))
    else:
        ignore_filters = []

    if not coder or coder.settings.get('calendar_filter_long', True):
        ignore_filters = ignore_filters + [{'id': 0, 'name': 'Disabled filter'}]

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

    promotion = Promotion.promoting.first()
    if promotion is not None:
        skip_promotion_ids = [request.COOKIES.get('_skip_promotion_id')]
        if coder is not None:
            skip_promotion_ids.append(coder.settings.get('skip_promotion_id'))
        skip_promotion_ids = [as_number(i) for i in skip_promotion_ids if i]
        if promotion.id in skip_promotion_ids:
            promotion = None

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
        "promotion": promotion,
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
    resources = Resource.priority_objects.all()
    resources = resources.select_related('module')

    more_fields = request.user.has_perm('clist.view_more_fields')
    more_fields = more_fields and [f for f in request.GET.getlist('more') if f] or []

    context = {
        'resources': resources,
        'params': {
            'more_fields': more_fields,
        },
        'navbar_database_viewname': 'clist_resource_changelist',
    }
    return render(request, 'resources.html', context)


@page_templates((('resources_account_rating_paging.html', None),))
@context_pagination()
def resources_account_ratings(request, template='resources_account_ratings.html'):
    params = {}
    accounts_filter = Q()

    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        coder_accounts_ids = set(coder.account_set.values_list('id', flat=True))
        primary_accounts = {a.resource_id: a for a in coder.primary_accounts().filter(rating__isnull=False)}
    else:
        coder = None
        coder_accounts_ids = set()
        primary_accounts = dict()

    resources = Resource.priority_objects.filter(has_rating_history=True)
    resources_ids = [r for r in request.GET.getlist('resource') if r]
    if resources_ids:
        params['resources'] = list(Resource.objects.filter(pk__in=resources_ids))
        resources = resources.filter(pk__in=resources_ids)

    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        params['countries'] = countries
        accounts_filter &= Q(country__in=countries)

    qs_key = request.GET.get(QS_KEY)
    if qs_key:
        _, host = qs_key.split('__')
        resources = resources.filter(host=host)

    list_values = [v for v in request.GET.getlist('list') if v]
    list_filter = CoderList.accounts_filter(list_values, coder=coder, logger=request.logger)
    if list_filter:
        qs = Account.objects.filter(list_filter).filter(rating__isnull=False).values_list('pk', flat=True)
        accounts_filter &= Q(pk__in=set(qs))

    for field, operator in (
        ('last_activity_from', 'last_activity__lte'),
        ('last_activity_to', 'last_activity__gte'),
    ):
        value = as_number(request.GET.get(field), force=True)
        if value is None:
            continue
        value = timezone.now() - timedelta(days=value)
        accounts_filter &= Q(**{operator: value})

    resources = list(resources)
    for resource in resources:
        accounts = resource.account_set.filter(rating__isnull=False).order_by('-rating')
        accounts = accounts.filter(accounts_filter)
        accounts = accounts.prefetch_related('coders')
        setattr(resource, 'accounts', accounts)

    earliest_last_activity = Account.objects.filter(rating__isnull=False).earliest('last_activity').last_activity

    context = {
        'resources': resources,
        'params': params,
        'coder_accounts_ids': coder_accounts_ids,
        'primary_accounts': primary_accounts,
        'last_activity': {
            'from': 0,
            'to': (timezone.now() - earliest_last_activity).days + 1,
        },
        'first_per_page': 10,
        'per_page': 50,
    }

    return render(request, template, context)


@page_templates((('resources_country_rating_paging.html', None),))
@context_pagination()
def resources_country_ratings(request, template='resources_country_ratings.html'):
    params = {}
    country_accounts = CountryAccount.objects.filter(rating__isnull=False).order_by('-rating')

    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        primary_countries_filter = Q()
        for account in coder.primary_accounts():
            primary_countries_filter |= Q(country=account.country) & Q(resource_id=account.resource_id)

        primary_countries = {
            country_account.resource_id: country_account
            for country_account in CountryAccount.objects.filter(primary_countries_filter)
        }

        qs = CountryAccount.objects.filter(primary_countries_filter | Q(country=coder.country))
        coder_country_accounts_ids = set()
        for country_account in qs:
            coder_country_accounts_ids.add(country_account.id)
            primary_countries.setdefault(country_account.resource_id, country_account)
    else:
        coder = None
        primary_countries = dict()
        coder_country_accounts_ids = set()

    resources = Resource.priority_objects.filter(has_country_rating=True)
    resources_ids = [r for r in request.GET.getlist('resource') if r]
    if resources_ids:
        params['resources'] = list(Resource.objects.filter(pk__in=resources_ids))
        resources = resources.filter(pk__in=resources_ids)

    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        params['countries'] = countries
        country_accounts = country_accounts.filter(country__in=countries)

    qs_key = request.GET.get(QS_KEY)
    if qs_key:
        _, host = qs_key.split('__')
        resources = resources.filter(host=host)

    resources = resources.annotate(has_country_accounts=Exists(country_accounts.filter(resource=OuterRef('pk'))))
    resources = resources.filter(has_country_accounts=True)
    resources = resources.prefetch_related(Prefetch('countryaccount_set',
                                                    queryset=country_accounts))

    resources = list(resources)

    context = {
        'resource': resources[0],
        'resources': resources,
        'params': params,
        'coder_country_accounts_ids': coder_country_accounts_ids,
        'primary_countries': primary_countries,
        'first_per_page': 10,
        'per_page': 50,
    }

    return render(request, template, context)


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
    ('resource_top_country_paging.html', 'top_country_page'),
    ('resource_last_activity_paging.html', 'last_activity_page'),
    ('resource_last_rating_activity_paging.html', 'last_rating_activity_page'),
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
        coder = request.as_coder or request.user.coder
        primary_account = coder.primary_account(resource)
        coder_accounts_ids = set(coder.account_set.filter(resource=resource).values_list('id', flat=True))
    else:
        coder = None
        primary_account = None
        coder_accounts_ids = set()

    if primary_account:
        primary_country = resource.countryaccount_set.filter(country=primary_account.country).first()
    else:
        primary_country = None

    params = {}
    mute_country_rating = False

    contests = resource.contest_set.all()

    accounts = Account.objects.filter(resource=resource)
    country_accounts = resource.countryaccount_set

    has_country = accounts.filter(country__isnull=False).exists()
    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        params['countries'] = countries
        accounts = accounts.filter(country__in=countries)
        country_accounts = country_accounts.filter(country__in=countries)

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
        mute_country_rating = True

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
            mute_country_rating = True

    if not request.as_coder:
        update_coder_range_filter(coder, range_filter_values, resource.host)

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
            ratings = ratings.filter(**{f'info__{coloring_field}__isnull': False})
            ratings = ratings.annotate(_rank=Cast(JSONF(f'info__{coloring_field}'), IntegerField()))
            aggregations = {'coloring_field': Avg('_rank')}
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
                        row['hex_rgb'] = '#eee'
                        continue
                    val = row['coloring_field']
                else:
                    val = int(row['rating'])
                while val > resource.ratings[idx]['high']:
                    idx += 1
                while val < resource.ratings[idx]['low']:
                    idx -= 1
                row['hex_rgb'] = resource.ratings[idx]['hex_rgb']
    else:
        rating_chart = None

    context = {
        'resource': resource,
        'coder': coder,
        'primary_account': primary_account,
        'primary_country': primary_country,
        'coder_accounts_ids': coder_accounts_ids,
        'accounts': resource.account_set.filter(coders__isnull=False).prefetch_related('coders').order_by('-modified'),
        'country_distribution': country_accounts.order_by(F('n_accounts').desc(nulls_last=True), 'country'),
        'country_ratings': (country_accounts
                            .filter(rating__isnull=False)
                            .order_by(F('rating').desc(nulls_last=True), 'country')),
        'rating': {
            'chart': rating_chart,
            'min': min_rating,
            'max': max_rating,
        },
        'contests': {
            'past': {
                'contests': contests.filter(end_time__lt=now).order_by('-end_time', '-id'),
                'field': 'end_time',
                'url': reverse('ranking:standings_list') + f'?resource={resource.pk}',
            },
            'coming': {
                'contests': contests.filter(start_time__gt=now).order_by('start_time', 'id'),
                'field': 'start_time',
                'url': reverse('clist:main') + f'?resource={resource.pk}&view=list&group=no&status=coming',
            },
            'running': {
                'contests': contests.filter(start_time__lt=now, end_time__gt=now).order_by('end_time', 'id'),
                'field': 'time_left',
                'url': reverse('clist:main') + f'?resource={resource.pk}&view=list&group=no&status=running',
            },
        },
        'contest_key': None,
        'has_country': has_country,
        'mute_country_rating': mute_country_rating,
        'periods': periods,
        'params': params,
        'first_per_page': 10,
        'per_page': 50,
        'last_activities': accounts.filter(last_activity__isnull=False).order_by('-last_activity', 'id'),
        'last_rating_activities': (accounts
                                   .filter(last_rating_activity__isnull=False)
                                   .order_by('-last_rating_activity', 'id')),
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


@transaction.atomic
def update_problems(contest, problems=None, force=False):
    if problems is not None and not force:
        if canonize(problems) == canonize(contest.info.get('problems')):
            return

    contest.info['problems'] = problems
    contest.save(update_fields=['info'])

    if hasattr(contest, 'stage'):
        return

    contest.n_problems = len(list(contest.problems_list))
    contest.save(update_fields=['n_problems'])

    contests_set = {contest.pk}
    contests_queue = SimpleQueue()
    contests_queue.put(contest)

    new_problem_ids = set()
    old_problem_ids = set(contest.problem_set.values_list('id', flat=True))
    old_problem_ids |= set(contest.individual_problem_set.values_list('id', flat=True))
    added_problems = dict()

    while not contests_queue.empty():
        current_contest = contests_queue.get()
        problem_sets = current_contest.division_problems
        for division, problem_set in problem_sets:
            prev = None
            for index, problem_info in enumerate(problem_set, start=1):
                key = get_problem_key(problem_info)
                short = get_problem_short(problem_info)
                name = get_problem_name(problem_info)

                if problem_info.get('ignore'):
                    continue
                if prev and not problem_info.get('_info_prefix'):
                    if prev.get('group') and prev.get('group') == problem_info.get('group'):
                        continue
                    if prev.get('subname') and prev.get('name') == name:
                        continue
                prev = deepcopy(problem_info)
                info = deepcopy(problem_info)

                problem_contest = contest if 'code' not in problem_info else None

                added_problem = added_problems.get(key)
                if current_contest != contest and not added_problem:
                    continue

                if problem_info.get('skip_in_stats'):
                    problem = Problem.objects.filter(
                        contest=problem_contest,
                        resource=contest.resource,
                        key=key,
                    ).first()
                    if problem:
                        problem.contests.add(contest)
                        if problem.id in old_problem_ids:
                            old_problem_ids.remove(problem.id)
                    continue

                url = info.pop('url', None)
                if info.pop('_no_problem_url', False):
                    url = getattr(added_problem, 'url', None) or url
                else:
                    url = url or getattr(added_problem, 'url', None)

                skip_rating = bool(contest.info.get('skip_problem_rating'))

                kinds = getattr(added_problem, 'kinds', [])
                if contest.kind and contest.kind not in kinds:
                    kinds.append(contest.kind)

                divisions = getattr(added_problem, 'divisions', [])
                if division and division not in divisions:
                    divisions.append(division)

                defaults = {
                    'index': index if getattr(added_problem, 'index', index) == index else None,
                    'short': short if getattr(added_problem, 'short', short) == short else None,
                    'name': name,
                    'slug': info.pop('slug', getattr(added_problem, 'slug', None)),
                    'divisions': divisions,
                    'kinds': kinds,
                    'url': url,
                    'n_attempts': info.pop('n_teams', 0) + getattr(added_problem, 'n_attempts', 0),
                    'n_accepted': info.pop('n_accepted', 0) + getattr(added_problem, 'n_accepted', 0),
                    'n_partial': info.pop('n_partial', 0) + getattr(added_problem, 'n_partial', 0),
                    'n_hidden': info.pop('n_hidden', 0) + getattr(added_problem, 'n_hidden', 0),
                    'n_total': info.pop('n_total', 0) + getattr(added_problem, 'n_total', 0),
                    'time': max(contest.start_time, getattr(added_problem, 'time', contest.start_time)),
                    'start_time': min(contest.start_time, getattr(added_problem, 'start_time', contest.start_time)),
                    'end_time': max(contest.end_time, getattr(added_problem, 'end_time', contest.end_time)),
                    'skip_rating': skip_rating and getattr(added_problem, 'skip_rating', skip_rating),
                }
                for optional_field in 'n_accepted_submissions', 'n_total_submissions':
                    if optional_field not in info:
                        continue
                    added_value = getattr(added_problem, optional_field, 0) or 0
                    defaults[optional_field] = info.pop(optional_field) + added_value
                if getattr(added_problem, 'rating', None) is not None:
                    problem_info['rating'] = added_problem.rating
                    info.pop('rating', None)
                elif 'rating' in info:
                    defaults['rating'] = info.pop('rating')
                if 'visible' in info:
                    defaults['visible'] = info.pop('visible')

                if 'archive_url' in info:
                    archive_url = info.pop('archive_url')
                elif contest.resource.problem_url:
                    archive_url = contest.resource.problem_url.format(key=key, **defaults)
                else:
                    archive_url = getattr(added_problem, 'archive_url', None)
                defaults['archive_url'] = archive_url

                if '_more_fields' in info:
                    info.update(info.pop('_more_fields'))
                info_prefix = info.pop('_info_prefix', None)
                info_prefix_fields = info.pop('_info_prefix_fields', None)
                if info_prefix:
                    for field in info_prefix_fields:
                        if field in info:
                            info[f'{info_prefix}{field}'] = info.pop(field)

                for field in 'short', 'code', 'name', 'tags', 'subname', 'subname_class':
                    info.pop(field, None)
                if added_problem:
                    added_info = deepcopy(added_problem.info or {})
                    added_info.update(info)
                    info = added_info
                defaults['info'] = info

                problem, created = Problem.objects.update_or_create(
                    contest=problem_contest,
                    resource=contest.resource,
                    key=key,
                    defaults=defaults,
                )
                problem.contests.add(contest)

                problem.update_tags(problem_info.get('tags'), replace=not added_problem)

                added_problems[key] = problem

                if problem.id in old_problem_ids:
                    old_problem_ids.remove(problem.id)
                new_problem_ids.add(problem.id)

                for c in problem.contests.all():
                    if c.pk in contests_set:
                        continue
                    contests_set.add(c.pk)
                    contests_queue.put(c)
        current_contest.save(update_fields=['info'])

    while old_problem_ids:
        new_problems = Problem.objects.filter(id__in=new_problem_ids)
        old_problems = Problem.objects.filter(id__in=old_problem_ids)

        max_similarity_score = 0
        for old_problem in old_problems:
            for new_problem in new_problems:
                similarity_score = 0
                for weight, field in (
                    (1, 'index'),
                    (2, 'short'),
                    (3, 'slug'),
                    (5, 'name'),
                    (10, 'url'),
                    (15, 'archive_url'),
                ):
                    similarity_score += weight * (getattr(old_problem, field) == getattr(new_problem, field))
                if similarity_score > max_similarity_score:
                    max_similarity_score = similarity_score
                    opt_old_problem = old_problem
                    opt_new_problem = new_problem
        if max_similarity_score == 0:
            break
        old_problem_ids.remove(opt_old_problem.id)
        opt_old_problem.contest = opt_new_problem.contest
        MergedModelInstance.create(opt_new_problem, [opt_old_problem])
        opt_old_problem.delete()

    if old_problem_ids:
        for problem in Problem.objects.filter(id__in=old_problem_ids):
            problem.contests.remove(contest)
            if problem.contests.count() == 0:
                problem.delete()

    return True


@page_templates((
    ('problems_paging.html', 'problems_paging'),
    ('standings_groupby_paging.html', 'groupby_paging'),
))
@context_pagination()
def problems(request, template='problems.html'):
    contests = [r for r in request.GET.getlist('contest') if r]
    problems = Problem.objects if contests else Problem.visible_objects

    problems = problems.annotate_favorite(request.user).annotate_note(request.user)
    problems = problems.select_related('resource', 'resource__module')
    problems_contests = Contest.objects.order_by('invisible', '-end_time', '-id')
    problems = problems.prefetch_related(Prefetch('contests', queryset=problems_contests))
    problems = problems.prefetch_related('tags')
    problems = problems.annotate(min_contest_id=SubqueryMin('contests__id'))
    problems = problems.annotate(date=F('time'))
    problems = problems.order_by(F('time').desc(nulls_last=True), '-min_contest_id', 'rating', 'index', 'short')

    show_tags = True
    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        has_update_coder = not bool(request.as_coder)
        show_tags = coder.settings.get('show_tags', show_tags)
        statistics = Statistics.objects.filter(account__coders=coder)
        accounts = Account.objects.filter(coders=coder, rating__isnull=False, resource=OuterRef('resource'))
        accounts = accounts.order_by('-rating').values('rating')[:1]
        problems = problems.annotate(account_rating=Subquery(accounts))
        problem_rating_accounts = (
            coder.account_set
            .filter(rating__isnull=False, resource__has_problem_rating=True)
            .select_related('resource')
        )

        problems = problems.annotate(luck=Cast(
            win_probability(F('rating'), F('account_rating')),
            output_field=FloatField(),
        ))

        content_type = ContentType.objects.get_for_model(Problem)
        qs = Activity.objects.filter(coder=coder, content_type=content_type, object_id=OuterRef('pk'))
        problems = problems.annotate(is_todo=Exists(qs.filter(activity_type=Activity.Type.TODO)))
        problems = problems.annotate(is_solved=Exists(qs.filter(activity_type=Activity.Type.SOLVED)))
        problems = problems.annotate(is_reject=Exists(qs.filter(activity_type=Activity.Type.REJECT)))
    else:
        coder = None
        has_update_coder = False
        statistics = Statistics.objects.none()
        problem_rating_accounts = []
    problems = problems.prefetch_related(Prefetch('contests__statistics_set', queryset=statistics))

    favorite = request.GET.get('favorite')
    if favorite in ['on', 'off']:
        if not coder:
            return redirect('auth:login')
        if favorite == 'on':
            problems = problems.filter(is_favorite=True)
        elif favorite == 'off':
            problems = problems.filter(is_favorite=False)

    show_tags_value = str(request.GET.get('show_tags', '')).lower()
    if show_tags_value:
        show_tags = show_tags_value in settings.YES_

    search = request.GET.get('search')
    if search:
        cond, problems = get_iregex_filter(
            search,
            'name', 'key',
            logger=request.logger,
            mapping={
                'name': {'fields': ['name__iregex']},
                'key': {'fields': ['key__iexact']},
                'index': {'fields': ['index']},
                'short': {'fields': ['short']},
                'contest': {'fields': ['contest__title__iregex'], 'exists': 'contests'},
                'resource': {'fields': ['resource__host__iregex']},
                'tag': {'fields': ['problemtag__name'], 'exists': 'tags'},
                'cid': {'fields': ['contest__pk'], 'exists': 'contests', 'func': lambda v: int(v)},
                'rid': {'fields': ['resource_id'], 'func': lambda v: int(v)},
                'pid': {'fields': ['id'], 'func': lambda v: int(v)},
                'n_accepted':  {'fields': ['n_accepted']},
                'n_partial':  {'fields': ['n_partial']},
                'n_hidden':  {'fields': ['n_hidden']},
                'n_total':  {'fields': ['n_total']},
                'archive': {'fields': ['is_archive'], 'func': lambda v: v in settings.YES_},
                'note': {'fields': ['note_text__iregex']},
                'year': {'fields': ['time__year']},
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

    if contests:
        problems = problems.annotate(has_contests=Exists('contests', filter=Q(contest__in=contests)))
        problems = problems.filter(Q(has_contests=True) | Q(contest__in=contests))
        contests = list(Contest.objects.filter(pk__in=contests))

    if len(resources) == 1:
        selected_resource = resources[0]
    elif len(contests) == 1:
        selected_resource = contests[0].resource
    else:
        selected_resource = None

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
        else:
            request.logger.warning('Luck filter is empty')

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
        for tag in tags:
            problems = problems.filter(tags__pk=tag)
        tags = list(ProblemTag.objects.filter(pk__in=tags))

    custom_fields = [f for f in request.GET.getlist('field') if f]
    custom_options = ['name', 'index', 'short', 'key', 'slug', 'url', 'archive_url', 'divisions', 'kinds',
                      'n_accepted', 'n_attempts', 'n_partial', 'n_hidden', 'n_total',
                      'n_accepted_submissions', 'n_total_submissions']
    custom_info_fields = set()
    if selected_resource:
        if selected_resource.has_new_problems:
            custom_options.append('is_archive')
        fixed_fields = selected_resource.problems_fields.get('fixed_fields', [])
        custom_fields = custom_fields + fixed_fields
        fixed_fields_set = set(fixed_fields)
        fields_types = selected_resource.problems_fields.get('types', {})
        for field in fields_types:
            if field not in custom_options:
                custom_options.append(field)
                custom_info_fields.add(field)
    else:
        fields_types = None
        fixed_fields_set = set()
    custom_fields_select = {
        'values': [v for v in custom_fields if v and v in custom_options],
        'options': [v for v in custom_options if v not in fixed_fields_set]
    }

    chart_select = {
        'values': [v for v in request.GET.getlist('chart') if v],
        'options': ['date', 'rating'] + (['luck'] if coder else []),
        'nomultiply': True,
    }
    chart_field = request.GET.get('chart')
    if chart_field == 'rating':
        step = selected_resource.rating_step() if selected_resource and selected_resource.has_rating_history else None
        chart = make_chart(problems, field='rating', step=step, logger=request.logger)
        if selected_resource and chart:
            for data in chart['data']:
                val = as_number(data['bin'], force=True)
                if val is None:
                    continue
                for rating in selected_resource.ratings:
                    if rating['low'] <= val <= rating['high']:
                        data['bgcolor'] = rating['hex_rgb']
                        break
    elif chart_field == 'date':
        chart = make_chart(problems, field='time', logger=request.logger)
    elif chart_field == 'luck' and coder:
        luck_from = 0 if luck_from is None else luck_from
        luck_to = 100 if luck_to is None else luck_to
        bins = make_bins(float(luck_from), float(luck_to), n_bins=40)
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

    status_select = {
        'values': [],
        'data': [
            {
                'id': (status_id := name if enable else f'no{name}'),
                'text': activity_icon(name, enable=enable),
                'selected': int(status_id in request.GET.getlist('status')),
            }
            for name in ['allsolved', 'allreject'] for enable in [True, False]
        ] + [
            {
                'id': (status_id := name if enable else f'no{name}'),
                'text': activity_icon(getattr(Activity.Type, name.upper()), enable=enable),
                'selected': int(status_id in request.GET.getlist('status')),
            }
            for name in ['todo', 'solved', 'reject'] for enable in [True, False]
        ] + [
            {
                'id': (status_id := name if enable else f'no{name}'),
                'text': activity_icon(name, enable=enable, name='note'),
                'selected': int(status_id in request.GET.getlist('status')),
            }
            for name in ['note'] for enable in [True, False]
        ],
        'html': True,
        'nomultiply': True,
    }
    statuses = [s for s in request.GET.getlist('status') if s]
    if statuses:
        if not coder:
            return redirect('auth:login')

        qs = CoderProblem.objects.filter(coder=coder, problem=OuterRef('pk'))
        problems = problems.annotate(is_solved_verdict=Exists(qs.filter(verdict=ProblemVerdict.SOLVED)))
        problems = problems.annotate(is_reject_verdict=Exists(qs.filter(verdict=ProblemVerdict.REJECT)))
        for status in statuses:
            if status.startswith('no') and status != 'note':
                status = status[2:]
                inverse = True
            else:
                inverse = False
            if status.startswith('all'):
                status = status[3:]
                with_verdicts = True
            else:
                with_verdicts = False
            if status in ['todo', 'solved', 'reject', 'note']:
                condition = Q(**{f'is_{status}': True})
                if with_verdicts:
                    if status == 'solved':
                        condition |= Q(is_solved_verdict=True)
                    elif status == 'reject':
                        condition |= Q(is_reject_verdict=True)
                if inverse:
                    condition = ~condition
                problems = problems.filter(condition)

    # group by
    groupby = request.GET.get('groupby')
    groupby_fields = OrderedDict()
    if groupby == 'tag':
        problems_subquery = problems.filter(tags=OuterRef('pk')).order_by().values('tags')
        problems_subquery = problems_subquery.annotate(cnt=Count('id')).values('cnt')
        groupby_data = ProblemTag.objects.annotate(n_problems=SubqueryCount(problems_subquery))
        groupby_data = groupby_data.filter(n_problems__gt=0)
        groupby_data = groupby_data.order_by('-n_problems', 'name')
        groupby_fields['name'] = 'Tag'
    elif groupby == 'resource':
        problems_subquery = problems.filter(resource=OuterRef('pk')).order_by().values('resource')
        problems_subquery = problems_subquery.annotate(cnt=Count('id')).values('cnt')
        groupby_data = Resource.objects.annotate(n_problems=SubqueryCount(problems_subquery))
        groupby_data = groupby_data.filter(n_problems__gt=0)
        groupby_data = groupby_data.order_by('-n_problems', 'host')
        groupby_fields['host'] = 'Resource'
    else:
        groupby = 'none'
        groupby_data = None
    groupby_fields['n_problems'] = 'Num'

    # sort problems
    sort_options = ['date', 'rating', 'name'] + [f for f in custom_fields_select['values']]
    sort_select = {'options': sort_options, 'rev_order': True}
    sort_field = request.GET.get('sort')
    sort_order = request.GET.get('sort_order')
    if sort_field and sort_field in sort_options and sort_order in ['asc', 'desc']:
        sort_select['values'] = [sort_field]
        if sort_field in custom_info_fields:
            sort_field = f'info__{sort_field}'
        orderby = getattr(F(sort_field), sort_order)(nulls_last=True)
        problems = problems.order_by(orderby)

    context = {
        'problems': problems,
        'coder': coder,
        'show_tags': show_tags,
        'params': {
            'resources': resources,
            'contests': contests,
            'tags': tags,
        },
        'chart_select': chart_select,
        'status_select': status_select,
        'sort_select': sort_select,
        'custom_fields_select': custom_fields_select,
        'custom_info_fields': custom_info_fields,
        'fields_types': fields_types,
        'chart': chart,
        'groupby': groupby,
        'groupby_data': groupby_data,
        'groupby_fields': groupby_fields,
        'groupby_select_first_column': True,
        'selected_resource': selected_resource,
        'per_page': 50,
        'per_page_more': 200,
        'navbar_database_viewname': 'clist_problem_changelist',
    }

    return template, context


def promo_links(request, template='links.html'):
    context = {'navbar_database_viewname': 'clist_promolink_changelist', 'links': PromoLink.enabled_objects.all()}
    return render(request, 'links.html', context)
