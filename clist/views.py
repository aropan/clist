from datetime import timedelta

import arrow
import pytz
from django.conf import settings
from django.db.models import F, Q, Count, OuterRef, Subquery, IntegerField, Exists
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from urllib.parse import urlparse, parse_qs


from clist.templatetags.extras import get_timezones
from clist.models import Resource, Contest, Banner
from true_coders.models import Party, Coder, Filter
from ranking.models import Rating, Statistics
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
        user_contest_filter = coder.get_contest_filter(['list'])
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
        contests = contests.prefetch_related('resource')
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


def get_timezone_offset(tzname):
    now = timezone.now()
    return now.astimezone(pytz.timezone(tzname)).utcoffset().total_seconds() // 60


@csrf_protect
def get_events(request):
    if request.user.is_authenticated:
        coder = request.user.coder
    else:
        coder = None

    referer = request.META.get('HTTP_REFERER')
    if referer:
        parsed = urlparse(referer)
        as_coder = parse_qs(parsed.query).get('as_coder')
        if as_coder and request.user.has_perm('as_coder'):
            coder = Coder.objects.get(user__username=as_coder[0])

    tzname = get_timezone(request)
    offset = get_timezone_offset(tzname)

    query = Q()
    categories = request.POST.getlist('categories')
    ignore_filters = request.POST.getlist('ignore_filters')
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

    try:
        result = []
        for contest in Contest.visible.filter(query):
            c = {
                'id': contest.pk,
                'title': contest.title,
                'host': contest.host,
                'url': contest.url,
                'start': (contest.start_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'end': (contest.end_time + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%S"),
                'countdown': contest.next_time,
                'color': contest.resource.color,
            }
            result.append(c)
    except Exception as e:
        return JsonResponse({'message': f'query = `{search_query}`, error = {e}'}, safe=False, status=400)
    return JsonResponse(result, safe=False)


def main(request):
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
        return HttpResponse("accepted")

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

    party_slug = request.GET.get("party")
    if party_slug is not None:
        party = get_object_or_404(Party.objects.for_user(request.user), slug=party_slug)
        context["party"] = {
            "id": party.id,
            "owner": party.author,
            "contest_ids": party.rating_set.values_list('contest__id', flat=True),
        }

    now = timezone.now()
    context.update({
        "offset": get_timezone_offset(tzname),
        "now": now,
        "viewmode": viewmode,
        "hide_contest": hide_contest,
        "timezone": tzname,
        "time_format": time_format,
        "open_new_tab": open_new_tab,
        "add_to_calendar": add_to_calendar,
        "banners": Banner.objects.filter(start_time__lte=now, end_time__gt=now),
    })

    return render(request, "main.html", context)


def resources(request):
    contests = Resource.objects.annotate(n_contests=Count('contest')).filter(pk=OuterRef('pk'))
    accounts = Resource.objects.annotate(n_accounts=Count('account')).filter(pk=OuterRef('pk'))
    resources = Resource.objects.select_related('module').annotate(
        n_contests=Subquery(contests.values('n_contests'), output_field=IntegerField()),
        n_accounts=Subquery(accounts.values('n_accounts'), output_field=IntegerField()),
    )
    resources = resources.annotate(priority=F('n_accounts') + F('n_contests'))
    resources = resources.order_by('-priority')
    return render(request, 'resources.html', {'resources': resources})


def resource(request, host):
    now = timezone.now()
    resource = get_object_or_404(Resource, host=host)
    has_statistics = Statistics.objects.filter(contest__resource=resource, contest_id=OuterRef('pk'))
    contests = resource.contest_set.filter(invisible=False).annotate(has_statistics=Exists(has_statistics))
    context = {
        'resource': resource,
        'accounts': resource.account_set.filter(coders__isnull=False).order_by('-modified'),
        'contests': [
            ('running', contests.filter(start_time__lt=now, end_time__gt=now).order_by('start_time')),
            ('coming', contests.filter(start_time__gt=now).order_by('start_time')),
            ('past', contests.filter(end_time__lt=now).order_by('-end_time')),
        ],
    }
    return render(request, 'resource.html', context)
