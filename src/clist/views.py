from collections import OrderedDict
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import arrow
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.core.management.commands import dumpdata
from django.db.models import Avg, Count, F, FloatField, Max, Min, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Cast
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit
from el_pagination.decorators import QS_KEY, page_templates
from sql_util.utils import Exists, SubqueryCount, SubqueryMin

from clist.models import Banner, Contest, Problem, ProblemTag, ProblemVerdict, PromoLink, Promotion, Resource
from clist.templatetags.extras import (allowed_redirect, as_number, get_item, get_problem_key, get_timezone_offset,
                                       is_yes, media_size, rating_from_probability, redirect_login, win_probability)
from favorites.models import Activity
from favorites.templatetags.favorites_extras import activity_icon
from notification.management.commands import sendout_tasks
from pyclist.decorators import context_pagination, pagination_login_required
from ranking.models import Account, CountryAccount, Rating, Statistics
from ranking.utils import get_participation_contests
from true_coders.models import Coder, CoderList, CoderProblem, Filter, Party
from utils.chart import TooManyBinsException, make_bins, make_chart
from utils.json_field import JSONF
from utils.regex import get_iregex_filter
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

    resources = request.get_resources()
    if resources:
        base_contests = base_contests.filter(resource__in=resources)
    search_query = request.GET.get('search_query', None)
    if search_query:
        base_contests = base_contests.filter(get_iregex_filter(search_query, 'host', 'title'))

    now = timezone.now()
    result = []
    status = request.GET.get('status')
    past_days = int(request.GET.get('past_days', 1))
    for group, query, order in (
        ("past", Q(start_time__gt=now - timedelta(days=past_days), end_time__lte=now), "end_time"),
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
    resources = request.get_resources(method='POST')
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
        query = Q(resource__in=resources)
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

    search_query = request.POST.get('search_query')
    if search_query:
        query &= get_iregex_filter(search_query, 'host', 'title')

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

    result = []
    for contest in contests.filter(query):
        color = contest.resource.color
        if past_action not in ['show', 'hide'] and contest.end_time < now:
            color = contest.resource.info.get('get_events', {}).get('colors', {}).get(past_action, color)

        start_time = (contest.start_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S")
        end_time = (contest.end_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S")
        c = {
            'id': contest.pk,
            'title': contest.title,
            'host': contest.host,
            'url': contest.actual_url,
            'start': start_time,
            'end': end_time,
            'countdown': contest.next_time_to(now),
            'hr_duration': contest.hr_duration,
            'color': color,
            'icon': media_size(contest.resource.icon_file.name, 32),
            'allDay': contest.full_duration >= timedelta(days=1),
        }
        if coder:
            c['favorite'] = contest.is_favorite
        result.append(c)
    return JsonResponse(result, safe=False)


@login_required
def send_event_notification(request):
    methods = request.POST.getlist('method')
    methods = set(methods)
    contest_id = request.POST['contest_id']
    message = request.POST['message']

    coder = request.user.coder

    if len(methods) > 10:
        return HttpResponseBadRequest('Too many methods')

    notifications = coder.get_notifications()
    notifications = {k for k, v in notifications}
    for method in methods:
        if method not in notifications:
            return HttpResponseBadRequest('Invalid method')

    for method in methods:
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

    more_fields = request.user.has_perm('clist.view_more_fields')
    more_fields = more_fields and [f for f in request.GET.getlist('more') if f] or []

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
        "more_fields": more_fields,
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
        'navbar_admin_model': Resource,
        'resources': resources,
        'params': {
            'more_fields': more_fields,
        },
    }
    return render(request, 'resources.html', context)


@pagination_login_required
@ratelimit(key="user_or_ip", rate="300/h")
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
    request_resources = request.get_resources()
    if request_resources:
        params['resources'] = list(request_resources)
        resources = resources.filter(pk__in=request_resources)

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


@pagination_login_required
@ratelimit(key="user_or_ip", rate="300/h")
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
    request_resources = request.get_resources()
    if request_resources:
        params['resources'] = list(request_resources)
        resources = resources.filter(pk__in=request_resources)

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
    n_bins, step = resource.rating_step()
    problems = resource.problem_set.all()
    problem_rating_chart = make_chart(problems, 'rating', n_bins=n_bins, cast='int', step=step)
    if not problem_rating_chart:
        return

    data = problem_rating_chart['data']
    idx = 0
    for idx, row in enumerate(data):
        row['title'] = f"{row['bin']}..{int(data[idx + 1]['bin']) - 1}" if idx + 1 < len(data) else row['bin']
        rating, _ = resource.get_rating_color(row['bin'], value_name='rating')
        if not rating:
            continue
        row['bgcolor'] = rating['hex_rgb']
        if 'name' in rating:
            row['subtitle'] = rating['name']

    problem_rating_chart['mode'] = 'index'
    problem_rating_chart['hover_mode'] = 'index'
    problem_rating_chart['border_color'] = '#fff'
    problem_rating_chart['bar_percentage'] = 1.0
    problem_rating_chart['category_percentage'] = 1.0
    return problem_rating_chart


@pagination_login_required
@ratelimit(key="user_or_ip", rate="300/h")
@page_templates((
    ('resource_country_most_medals.html', 'country_most_medals_page'),
    ('resource_top_country_paging.html', 'top_country_page'),
    ('resource_country_distribution_paging.html', 'country_distribution_page'),
    ('resource_last_submission_paging.html', 'last_submission_page'),
    ('resource_last_activity_paging.html', 'last_activity_page'),
    ('resource_last_rating_activity_paging.html', 'last_rating_activity_page'),
    ('resource_top_paging.html', 'top_page'),
    ('resource_most_participated_paging.html', 'most_participated_page'),
    ('resource_most_writer_paging.html', 'most_writer_page'),
    ('resource_most_solved_paging.html', 'most_solved_page'),
    ('resource_most_first_ac_paging.html', 'most_first_ac_page'),
    ('resource_most_total_solving_paging.html', 'most_total_solving_page'),
    ('resource_most_medals_paging.html', 'most_medals_page'),
    ('resource_most_places_paging.html', 'most_places_page'),
    ('resource_contests.html', 'past_page'),
    ('resource_contests.html', 'coming_page'),
    ('resource_contests.html', 'running_page'),
    ('resource_problems_paging.html', 'problems_page'),
))
def resource(request, resource, template='resource.html', extra_context=None):
    page_template = extra_context.get('page_template')
    now = timezone.now()
    resource = Resource.get(resource)
    request.set_canonical(reverse('clist:resource', args=[resource.pk]))

    action = request.POST.get('action')
    if action:
        if action == 'set_verification_fields' and request.user.has_perm('clist.change_resource'):
            verification_fields = request.get_filtered_list(
                'verification_fields',
                options=resource.account_verification_fields_options,
                method='POST',
            )
            if not resource.has_account_verification:
                request.logger.error(f'Account verification is not enabled for {resource}')
            elif not verification_fields:
                request.logger.error(f'No fields selected for {resource}')
            else:
                request.logger.success(f'Verification fields for {resource} updated = {verification_fields}')
                resource.accounts_fields['verification_fields'] = verification_fields
                resource.save(update_fields=['accounts_fields'])
        return allowed_redirect(request.get_full_path())

    if request.user.is_authenticated:
        coder = request.as_coder or request.user.coder
        coder_accounts_ids = set(coder.account_set.filter(resource=resource).values_list('id', flat=True))
    else:
        coder = None
        coder_accounts_ids = set()

    params = {}
    mute_country_rating = False

    contests = resource.contest_set.all()

    accounts = Account.objects.filter(resource=resource)
    country_accounts = resource.countryaccount_set
    if account_type := Account.get_type(account_type_value := request.GET.get('account_type')):
        accounts = accounts.filter(account_type=account_type)
        params['account_type'] = account_type_value
        mute_country_rating = True
    elif resource.has_account_types:
        params['account_type'] = Account.get_type_value(resource.default_account_type)
        accounts = accounts.filter(account_type=resource.default_account_type)

    if coder_kind := request.GET.get('coder_kind'):
        accounts = Account.apply_coder_kind(accounts, coder_kind, logger=request.logger)
        params['coder_kind'] = coder_kind
        mute_country_rating = True

    has_country = accounts.filter(country__isnull=False).exists()
    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        params['countries'] = countries
        accounts = accounts.filter(country__in=countries)
        country_accounts = country_accounts.filter(country__in=countries)

    period = request.GET.get('period')
    deltas_period = {
        'year': timedelta(days=30 * 12),
        'half': timedelta(days=30 * 6),
        'quarter': timedelta(days=30 * 3),
        'month': timedelta(days=30 * 1),
    }
    delta_period = deltas_period.get(period, None)
    if delta_period:
        accounts = accounts.filter(last_activity__gte=now - delta_period)
        mute_country_rating = True
    period_select = {
        'options': list(deltas_period.keys()),
        'nomultiply': True,
    }

    list_uuids = [v for v in request.GET.getlist('list') if v]
    if list_uuids:
        accounts_filter = CoderList.accounts_filter(list_uuids, coder=coder, logger=request.logger)
        accounts = accounts.filter(accounts_filter)
        accounts_annotate = CoderList.accounts_annotate(list_uuids)
        accounts = accounts.annotate(value_instead_key=accounts_annotate)
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

    resource_ratings = resource.ratings
    if not resource_ratings and resource.has_rating_history:
        resource_ratings = [{'low': float('-inf'), 'high': float('inf'), 'hex_rgb': '#999'}]
    if resource_ratings and not page_template:
        values = resource.account_set.aggregate(min_rating=Min('rating'), max_rating=Max('rating'))
        min_rating = values['min_rating']
        max_rating = values['max_rating']

        ratings = accounts.filter(rating__isnull=False)
        rating_field = 'rating'

        n_bins, step = resource.rating_step()

        coloring_field = get_item(resource.info, 'ratings.chartjs.coloring_field')
        if coloring_field:
            ratings = ratings.filter(**{f'info__{coloring_field}__isnull': False})
            ratings = ratings.annotate(_rank=Cast(JSONF(f'info__{coloring_field}'), FloatField()))
            aggregations = {'coloring_field': Avg('_rank')}
        else:
            aggregations = None

        try:
            rating_chart = make_chart(ratings, rating_field, n_bins=n_bins, step=step, aggregations=aggregations)
        except TooManyBinsException as e:
            rating_chart = None
            request.logger.error(f'Rating chart for {resource} failed: {e}')

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
                while idx + 1 < len(resource_ratings[idx]) and val >= resource_ratings[idx]['high']:
                    idx += 1
                while idx - 1 > 0 and val < resource_ratings[idx]['low']:
                    idx -= 1
                row['hex_rgb'] = resource_ratings[idx]['hex_rgb']
    else:
        rating_chart = None
        min_rating = None
        max_rating = None

    verification_fields_select = None
    if resource.has_account_verification:
        verification_fields_select = {
            'values': resource.account_verification_fields,
            'options': resource.account_verification_fields_options,
            'collapse': True,
            'icon': 'verification',
        }

    primary_account = coder.primary_account(accounts=accounts) if coder else None
    if primary_account:
        primary_country = resource.countryaccount_set.filter(country=primary_account.country).first()
    else:
        primary_country = None

    medals_order = [F(f).desc(nulls_last=True) for f in ('n_win', 'n_gold', 'n_silver', 'n_bronze', 'n_other_medals')]
    places_order = [F(f).desc(nulls_last=True) for f in ('n_first_places', 'n_second_places', 'n_third_places',
                                                         'n_top_ten_places')]

    def get_ordered_by_nullable_field(qs, field):
        return qs.order_by(F(field).desc(nulls_last=True), 'id').filter(**{f'{field}__isnull': False})

    def get_ordered_by_number_field(qs, field):
        return qs.order_by(F(field).desc(nulls_last=True), 'id').filter(**{f'{field}__gt': 0})

    context = {
        'resource': resource,
        'period_select': period_select,
        'verification_fields_select': verification_fields_select,
        'coder': coder,
        'primary_account': primary_account,
        'primary_country': primary_country,
        'coder_accounts_ids': coder_accounts_ids,
        'accounts': resource.account_set.filter(coders__isnull=False).prefetch_related('coders').order_by('-modified'),
        'country_distribution': get_ordered_by_number_field(country_accounts, 'n_accounts'),
        'country_ratings': get_ordered_by_nullable_field(country_accounts, 'rating'),
        'country_medals': get_ordered_by_nullable_field(country_accounts, 'n_medals').order_by(*medals_order, 'id'),
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
        'mute_problems': mute_country_rating,
        'mute_contests': mute_country_rating,
        'params': params,
        'first_per_page': 10,
        'per_page': 50,
        'last_submissions': get_ordered_by_nullable_field(accounts, 'last_submission'),
        'last_activities': get_ordered_by_nullable_field(accounts, 'last_activity'),
        'last_rating_activities': get_ordered_by_nullable_field(accounts, 'last_rating_activity'),
        'top': get_ordered_by_nullable_field(accounts, 'rating'),
        'most_participated': get_ordered_by_number_field(accounts, 'n_contests'),
        'most_writer': get_ordered_by_number_field(accounts, 'n_writers'),
        'most_solved': get_ordered_by_number_field(accounts, 'n_total_solved'),
        'most_first_ac': get_ordered_by_number_field(accounts, 'n_first_ac'),
        'most_total_solving': get_ordered_by_number_field(accounts, 'total_solving'),
        'most_medals': get_ordered_by_nullable_field(accounts, 'n_medals').order_by(*medals_order, 'id'),
        'most_places': get_ordered_by_nullable_field(accounts, 'n_places').order_by(*places_order, 'id'),
        'problems': resource.problem_set.filter(url__isnull=False).order_by('-time', 'contest_id', 'index'),
    }

    if page_template:
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


@pagination_login_required
@ratelimit(key="user_or_ip", rate="300/h")
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
            return redirect_login(request)
        if favorite == 'on':
            problems = problems.filter(is_favorite=True)
        elif favorite == 'off':
            problems = problems.filter(is_favorite=False)

    if participation := request.GET.get('participation'):
        participation_operator, participation_contests = get_participation_contests(request, participation)
        problems = getattr(problems, participation_operator)(contests__in=participation_contests)

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

    resources = request.get_resources()
    if resources:
        problems = problems.filter(resource__in=resources)
        if coder:
            problem_rating_accounts = problem_rating_accounts.filter(resource__in=resources)

    contest_problems = None
    if contests:
        problems = problems.annotate(has_contests=Exists('contests', filter=Q(contest__in=contests)))
        problems = problems.filter(Q(has_contests=True) | Q(contest__in=contests))
        contests = list(Contest.objects.filter(pk__in=contests))
        if len(contests) == 1:
            contest_problems = {}
            for problem in contests[0].full_problems_list:
                problem_key = get_problem_key(problem)
                if problem_key in contest_problems:
                    contest_problems = None
                    break
                contest_problems[problem_key] = problem

    if len(resources) == 1:
        selected_resource = resources[0]
    elif len(contests) == 1:
        selected_resource = contests[0].resource
    else:
        selected_resource = None

    list_uuids = request.get_filtered_list('list')
    if list_uuids:
        problems_coder_lists = CoderList.filter_for_coder(coder).filter(uuid__in=list_uuids)
        has_coder_lists_filter = problems_coder_lists.filter(problems__problem_id=OuterRef('pk'))
        problems = problems.annotate(has_coder_lists=Exists(has_coder_lists_filter))
        problems = problems.filter(has_coder_lists=True)

    range_filter_values = {}
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
                      'n_accepted_submissions', 'n_total_submissions',
                      'attempt_rate', 'acceptance_rate', 'partial_rate', 'hidden_rate']
    custom_info_fields = set()
    if selected_resource:
        if selected_resource.has_problem_archive:
            custom_options.append('is_archive')
        fixed_fields = selected_resource.problems_fields.get('fixed_fields', [])
        if contests:
            fixed_fields.append('short')
        fixed_fields_set = set(fixed_fields)
        fields_types = selected_resource.problems_fields.get('types', {})
        for field in fields_types:
            if field not in custom_options:
                custom_options.append(field)
                custom_info_fields.add(field)
    else:
        fields_types = dict()
        fixed_fields = []
        fixed_fields_set = set()
    custom_fields_select = {
        'values': [v for v in custom_fields if v and v in custom_options],
        'options': [v for v in custom_options if v not in fixed_fields_set]
    }
    custom_fields += fixed_fields

    filter_fields = []
    for field in custom_options:
        field_types = fields_types.get(field)
        if not field_types or any(t in field_types for t in ('int', 'float', 'dict')):
            continue
        values_list = request.get_filtered_list(field + settings.FILTER_FIELD_SUFFIX)
        if values_list:
            values_filter = Q()
            for value in values_list:
                key = f'info__{field}'
                if value == 'none':
                    key = f'{key}__isnull'
                    value = True
                if 'bool' in field_types:
                    value = is_yes(value)
                if 'list' in field_types:
                    key = f'{key}__contains'
                values_filter |= Q(**{key: value})
            problems = problems.filter(values_filter)
        if field not in custom_fields and not values_list:
            continue
        filter_fields.append(field)

    chart_select = {
        'values': [v for v in request.GET.getlist('chart') if v],
        'options': ['date', 'rating'] + (['luck'] if coder else []),
        'nomultiply': True,
    }
    chart_field = request.GET.get('chart')
    if chart_field == 'rating':
        n_bins, step = (
            selected_resource.rating_step()
            if selected_resource and selected_resource.has_rating_history else
            (None, None)
        )
        chart = make_chart(problems, field='rating', n_bins=n_bins, step=step, logger=request.logger)
        if selected_resource and chart:
            for data in chart['data']:
                rating, _ = selected_resource.get_rating_color(data['bin'], value_name='rating')
                if rating:
                    data['bgcolor'] = rating['hex_rgb']
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
            return redirect_login(request)

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
    sort_options = ['date', 'rating', 'name'] + custom_fields
    sort_select = {'options': sort_options, 'rev_order': True}
    sort_field = request.GET.get('sort')
    sort_order = request.GET.get('sort_order')
    if sort_field and sort_field in sort_options and sort_order in ['asc', 'desc']:
        sort_select['values'] = [sort_field]
        if sort_field in custom_info_fields:
            sort_field = f'info__{sort_field}'
        orderby = getattr(F(sort_field), sort_order)(nulls_last=True)
        problems = problems.order_by(orderby)

    # hidden fields
    hidden_fields = set()
    if resources:
        if not any(resource.has_problem_rating for resource in resources):
            hidden_fields.add('rating')
            hidden_fields.add('luck')
        if not any(resource.has_problem_statistic for resource in resources):
            hidden_fields.add('stats')
            hidden_fields.add('result')

    context = {
        'navbar_admin_model': Problem,
        'resources': resources,
        'problems': problems,
        'contest_problems': contest_problems,
        'selected_resource': selected_resource,
        'hidden_fields': hidden_fields,
        'coder': coder,
        'show_tags': show_tags,
        'params': {
            'resources': resources,
            'contests': contests,
            'tags': tags,
        },
        'filter_fields': filter_fields,
        'chart_select': chart_select,
        'status_select': status_select,
        'sort_select': sort_select,
        'custom_fields': custom_fields,
        'custom_fields_select': custom_fields_select,
        'custom_info_fields': custom_info_fields,
        'fields_types': fields_types,
        'chart': chart,
        'groupby': groupby,
        'groupby_data': groupby_data,
        'groupby_fields': groupby_fields,
        'groupby_select_first_column': True,
        'per_page': 50,
        'per_page_more': 200,
    }

    return template, context


def promo_links(request, template='links.html'):
    context = {'navbar_admin_model': PromoLink, 'links': PromoLink.enabled_objects.all()}
    return render(request, 'links.html', context)
