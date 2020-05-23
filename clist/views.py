from datetime import timedelta
from urllib.parse import urlparse, parse_qs

import arrow
import pytz
from django.conf import settings
from django.db.models.functions import Cast, Ln
from django.db.models import F, Q, Count, IntegerField, FloatField
from django.core.management.commands import dumpdata
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from sql_util.utils import Exists
from el_pagination.decorators import page_templates

from clist.templatetags.extras import get_timezones, get_timezone_offset, slug
from clist.models import Resource, Contest, Banner
from true_coders.models import Party, Coder, Filter
from ranking.models import Rating, Account
from utils.regex import verify_regex


def get_timeformat(request):
    ret = settings.TIME_FORMAT_
    if request.user.is_authenticated:
        ret = request.user.coder.settings.get("time_format", ret)
    return ret


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

    if request.user.is_authenticated:
        return request.user.coder.timezone
    return request.session.get("timezone", settings.DEFAULT_TIME_ZONE_)


def get_view_contests(request, coder):
    user_contest_filter = Q()
    group_list = settings.GROUP_LIST_

    if coder:
        categories = request.GET.getlist('filter', ['list'])
        user_contest_filter = coder.get_contest_filter(categories)
        group_list = bool(coder.settings.get("group_in_list", group_list))

    group = request.GET.get('group')
    if group is not None:
        group_list = bool(group)

    now = timezone.now()
    result = []
    for group, query, order, limit in (
        ("past", Q(start_time__gt=now - timedelta(days=1), end_time__lt=now), "-end_time", settings.COUNT_PAST_),
        ("running", Q(start_time__lte=now, end_time__gte=now), "end_time", None),
        ("coming", Q(start_time__gt=now), "start_time", None),
    ):
        group_by_resource = {}
        contests = Contest.visible.filter(query).filter(user_contest_filter).order_by(order)
        contests = contests.select_related('resource')
        contests = contests.annotate(has_statistics=Exists('statistics'))
        if limit:
            contests = contests[:limit]
        if order.startswith('-'):
            contests = list(contests)
            contests.reverse()
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


@csrf_protect
def get_events(request):
    if request.user.is_authenticated:
        coder = request.user.coder
    else:
        coder = None

    categories = request.POST.getlist('categories')
    ignore_filters = request.POST.getlist('ignore_filters')

    referer = request.META.get('HTTP_REFERER')
    if referer:
        parsed = urlparse(referer)
        query_dict = parse_qs(parsed.query)
        as_coder = query_dict.get('as_coder')
        if as_coder and request.user.has_perm('as_coder'):
            coder = Coder.objects.get(user__username=as_coder[0])
        categories = query_dict.get('filter', categories)

    tzname = get_timezone(request)
    offset = get_timezone_offset(tzname)

    query = Q()
    if coder:
        query = coder.get_contest_filter(categories, ignore_filters)

    if not coder or coder.settings.get('calendar_filter_long', True):
        if categories == ['calendar'] and '0' not in ignore_filters:
            query &= Q(duration_in_secs__lt=timedelta(days=1).total_seconds())

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

    try:
        result = []
        for contest in contests.filter(query):
            c = {
                'id': contest.pk,
                'title': contest.title,
                'host': contest.host,
                'url': (
                    reverse('ranking:standings', args=(slug(contest.title), contest.pk))
                    if contest.has_statistics else
                    contest.standings_url or contest.url
                ),
                'start': (contest.start_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'end': (contest.end_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'countdown': contest.next_time,
                'hr_duration': contest.hr_duration,
                'color': contest.resource.color,
            }
            result.append(c)
    except Exception as e:
        return JsonResponse({'message': f'query = `{search_query}`, error = {e}'}, safe=False, status=400)
    return JsonResponse(result, safe=False)


def main(request, party=None):
    viewmode = settings.VIEWMODE_
    open_new_tab = settings.OPEN_NEW_TAB_
    add_to_calendar = settings.ADD_TO_CALENDAR_
    hide_contest = settings.HIDE_CONTEST_

    if request.user.is_authenticated:
        if request.GET.get('as_coder') and request.user.has_perm('as_coder'):
            coder = Coder.objects.get(user__username=request.GET['as_coder'])
        else:
            coder = request.user.coder
        viewmode = coder.settings.get("view_mode", viewmode)
        hide_contest = coder.settings.get("hide_contest", hide_contest)
        open_new_tab = coder.settings.get("open_new_tab", open_new_tab)
        add_to_calendar = coder.settings.get("add_to_calendar", add_to_calendar)
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

    tzname = get_timezone(request)
    if tzname is None:
        return HttpResponse("accepted")

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
    timezone_hm = f'{"+" if offset > 0 else "-"}{abs(offset // 60):02d}:{abs(offset % 60):02d}'

    context.update({
        "offset": offset,
        "now": now,
        "viewmode": viewmode,
        "hide_contest": hide_contest,
        "timezone": tzname,
        "timezone_hm": timezone_hm,
        "time_format": time_format,
        "open_new_tab": open_new_tab,
        "add_to_calendar": settings.ACE_CALENDARS_[add_to_calendar]['id'],
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
    ('resource_contests.html', 'past_page'),
    ('resource_contests.html', 'coming_page'),
    ('resource_contests.html', 'running_page'),
))
def resource(request, host, template='resource.html', extra_context=None):
    now = timezone.now()
    resource = get_object_or_404(Resource, host=host)
    min_rating = request.GET.get('min_rating')
    max_rating = request.GET.get('max_rating')

    if request.user.is_authenticated:
        coder = request.user.coder
        coder_account = coder.account_set.filter(resource=resource, rating__isnull=False).first()
        coder_account_ids = set(coder.account_set.filter(resource=resource).values_list('id', flat=True))
        show_coder_account_rating = not min_rating and not max_rating
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
    if min_rating:
        accounts = accounts.filter(rating__gte=int(min_rating))
    if max_rating:
        accounts = accounts.filter(rating__lte=int(max_rating))

    countries = accounts \
        .filter(country__isnull=False) \
        .values('country') \
        .annotate(count=Count('country')) \
        .order_by('-count', 'country')

    width = 50
    if min_rating and max_rating and int(max_rating) - int(min_rating) <= 100:
        width = 1

    rating_field = 'rating50' if width == 50 else 'rating'

    ratings = accounts \
        .filter(**{f'{rating_field}__isnull': False}) \
        .values(rating_field) \
        .annotate(count=Count(rating_field)) \
        .order_by(rating_field)
    ratings = list(ratings)

    labels = []
    data = []
    if ratings and resource.ratings:
        idx = 0
        for rating in ratings:
            low = rating[rating_field] * width
            high = low + width - 1

            while low > resource.ratings[idx]['high']:
                idx += 1
            data.append({
                'title': f'{low}..{high}',
                'rating': low,
                'count': rating['count'],
                'info': resource.ratings[idx],
            })
        min_rating = ratings[0][rating_field]
        max_rating = ratings[-1][rating_field]
        if coder_account and show_coder_account_rating:
            min_rating = min(min_rating, coder_account.rating // width)
            max_rating = max(max_rating, coder_account.rating // width)
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
            'running': {
                'contests': contests.filter(start_time__lt=now, end_time__gt=now).order_by('end_time'),
                'field': 'time_left',
            },
            'coming': {
                'contests': contests.filter(start_time__gt=now).order_by('start_time'),
                'field': 'start_time',
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
