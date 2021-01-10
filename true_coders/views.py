import collections
import re
import json
import logging

import pytz
from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db import transaction
from django.db.models.functions import Cast
from django.db.models import Count, F, Q, Case, When, Value, OuterRef, BooleanField, IntegerField, Prefetch
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from tastypie.models import ApiKey
from django_countries import countries
from el_pagination.decorators import page_templates, page_template
from sql_util.utils import SubqueryMax, SubqueryCount, SubquerySum, Exists

from clist.models import Resource, Contest
from clist.templatetags.extras import get_timezones, format_time, slug as slugify, query_transform
from clist.views import get_timezone, get_timeformat, main
from events.models import Team, TeamStatus
from my_oauth.models import Service
from notification.forms import Notification, NotificationForm
from ranking.models import Rating, Statistics, Module, Account, update_account_by_coders
from true_coders.models import Filter, Party, Coder, Organization
from utils.regex import verify_regex, get_iregex_filter
from pyclist.decorators import context_pagination


logger = logging.getLogger(__name__)


def get_profile_context(request, statistics, writers):
    history_resources = statistics \
        .filter(contest__resource__has_rating_history=True) \
        .filter(contest__stage__isnull=True) \
        .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
        .filter(new_rating__isnull=False) \
        .annotate(host=F('contest__resource__host')) \
        .values('host') \
        .annotate(num_contests=Count('contest')) \
        .order_by('-num_contests')

    stats = statistics \
        .select_related('contest', 'account') \
        .filter(addition__medal__isnull=False) \
        .order_by('-contest__end_time')
    resource_medals = {}
    account_medals = {}
    for stat in stats:
        resource_medals.setdefault(stat.contest.resource_id, []).append(stat)
        account_medals.setdefault(stat.account.id, []).append(stat)

    statistics = statistics \
        .select_related('contest', 'contest__resource', 'account') \
        .order_by('-contest__end_time')

    search = request.GET.get('search')
    filters = {}
    if search:
        filt = get_iregex_filter(
            search,
            'contest__resource__host', 'contest__title',
            mapping={
                'writer': {'fields': ['contest__info__writers__contains']},
                'contest': {'fields': ['contest__title__iregex']},
                'resource': {'fields': ['contest__resource__host']},
                'account': {'fields': ['account__key']},
                'medal': {
                    'fields': ['addition__medal'],
                    'func': lambda v: False if not v or v == 'any' else v,
                    'suff': lambda v: '__isnull' if v is False else '',
                },
                'cid': {'fields': ['contest_id'], 'func': lambda v: int(v)},
                'rid': {'fields': ['contest__resource_id'], 'func': lambda v: int(v)},
            },
            values=filters,
            logger=request.logger,
        )
        statistics = statistics.filter(filt)

    filter_resources = filters.pop('resource', [])
    for val in filter_resources:
        history_resources = history_resources.filter(contest__resource__host=val)
    search_resource = filter_resources[0] if len(filter_resources) == 1 else None

    if search_resource:
        writers = writers.filter(resource__host=search_resource)
    writers = writers.order_by('-end_time')
    writers = writers.annotate(has_statistics=Exists('statistics'))

    context = {
        'statistics': statistics,
        'writers': writers,
        'history_resources': history_resources,
        'show_history_ratings': not filters,
        'resource_medals': resource_medals,
        'account_medals': account_medals,
        'search_resource': search_resource,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
    }

    return context


@login_required
def coder_profile(request):
    url = reverse('coder:profile', args=[request.user.coder.username])
    query = query_transform(request)
    if query:
        url += '?' + query
    return HttpResponseRedirect(url)


@page_template('coders_paging.html')
@context_pagination()
def coders(request, template='coders.html'):
    coders = Coder.objects.select_related('user')
    params = {}

    search = request.GET.get('search')
    if search:
        filt = get_iregex_filter(search, 'username', logger=request.logger)
        coders = coders.filter(filt)

    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        coders = coders.annotate(filter_country=Exists('account', filter=Q(account__country__in=countries)))
        coders = coders.filter(Q(country__in=countries) | Q(filter_country=True))
        params['countries'] = countries

    resources = request.GET.getlist('resource')
    if resources:
        resources = [r for r in resources if r]
        resources = list(Resource.objects.filter(pk__in=resources))
        for r in resources:
            coders = coders.annotate(**{f'{r.pk}_rating': SubqueryMax('account__rating', filter=Q(resource=r))})
            coders = coders.annotate(**{f'{r.pk}_n_contests': SubquerySum('account__n_contests', filter=Q(resource=r))})
        params['resources'] = resources

    # ordering
    orderby = request.GET.get('sort_column')
    if orderby in ['username', 'created', 'n_accounts']:
        pass
    elif orderby and orderby.startswith('resource_'):
        _, pk = orderby.split('_')
        orderby = [f'{pk}_rating', f'{pk}_n_contests']
    elif orderby:
        request.logger.error(f'Not found `{orderby}` column for sorting')
        orderby = []
    orderby = orderby if not orderby or isinstance(orderby, list) else [orderby]
    order = request.GET.get('sort_order')
    if order in ['asc', 'desc']:
        orderby = [getattr(F(o), order)(nulls_last=True) for o in orderby]
    elif order:
        request.logger.error(f'Not found `{order}` order for sorting')
    orderby = orderby or ['-created']
    coders = coders.order_by(*orderby)

    context = {
        'coders': coders,
        'params': params,
    }
    return template, context


@page_templates((
    ('profile_contests_paging.html', 'contest_page'),
    ('profile_writers_paging.html', 'writers_page'),
))
def profile(request, username, template='profile.html', extra_context=None):
    coder = get_object_or_404(Coder, user__username=username)
    statistics = Statistics.objects.filter(account__coders=coder)

    resources = Resource.objects \
        .prefetch_related(Prefetch(
            'account_set',
            queryset=(
                Account.objects
                .filter(coders=coder)
                .order_by('-n_contests')
            ),
            to_attr='coder_accounts',
        )) \
        .annotate(num_contests=SubquerySum('account__n_contests', filter=Q(coders=coder))) \
        .filter(num_contests__gt=0).order_by('-num_contests')

    writers = Contest.objects.filter(writers__coders=coder)
    context = get_profile_context(request, statistics, writers)

    if context['search_resource']:
        resources = resources.filter(host=context['search_resource'])

    context['coder'] = coder
    context['resources'] = resources

    if extra_context is not None:
        context.update(extra_context)
    return render(request, template, context)


@page_templates((
    ('profile_contests_paging.html', 'contest_page'),
    ('profile_writers_paging.html', 'writers_page'),
))
def account(request, key, host, template='profile.html', extra_context=None):
    accounts = Account.objects.select_related('resource').prefetch_related('coders')
    account = get_object_or_404(accounts, key=key, resource__host=host)
    statistics = Statistics.objects.filter(account=account)

    writers = Contest.objects.filter(writers=account).order_by('-end_time')
    context = get_profile_context(request, statistics, writers)
    context['account'] = account

    add_account_button = False
    if request.user.is_authenticated:
        module = getattr(account.resource, 'module', None)
        coder_accounts = request.user.coder.account_set.filter(resource=account.resource)
        if module and (module.multi_account_allowed or not coder_accounts.first()):
            add_account_button = True
    else:
        add_account_button = True
    context['add_account_button'] = add_account_button

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


def get_ratings_data(request, username=None, key=None, host=None, statistics=None, date_from=None, date_to=None):
    if statistics is None:
        if username is not None:
            coder = get_object_or_404(Coder, user__username=username)
            statistics = Statistics.objects.filter(account__coders=coder)
        else:
            account = get_object_or_404(Account, key=key, resource__host=host)
            statistics = Statistics.objects.filter(account=account)

    resources = {r.pk: r for r in Resource.objects.filter(has_rating_history=True)}

    qs = statistics \
        .annotate(date=F('contest__end_time')) \
        .annotate(name=F('contest__title')) \
        .annotate(stage=F('contest__stage')) \
        .annotate(resource=F('contest__resource')) \
        .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
        .annotate(old_rating=Cast(KeyTextTransform('old_rating', 'addition'), IntegerField())) \
        .annotate(rating_change=Cast(KeyTextTransform('rating_change', 'addition'), IntegerField())) \
        .annotate(score=F('solving')) \
        .annotate(addition_solved=KeyTextTransform('solved', 'addition')) \
        .annotate(solved=Cast(KeyTextTransform('solving', 'addition_solved'), IntegerField())) \
        .annotate(problems=KeyTextTransform('problems', 'contest__info')) \
        .annotate(division=KeyTextTransform('division', 'addition')) \
        .annotate(cid=F('contest__pk')) \
        .annotate(is_unrated=Cast(KeyTextTransform('is_unrated', 'contest__info'), IntegerField())) \
        .filter(Q(is_unrated__isnull=True) | Q(is_unrated=0)) \
        .filter(new_rating__isnull=False) \
        .order_by('date') \

    qs = qs.values(
        'cid',
        'name',
        'date',
        'new_rating',
        'old_rating',
        'rating_change',
        'place',
        'score',
        'solved',
        'problems',
        'division',
        'addition___rating_data',
        'resource',
        'stage',
    )

    ratings = {
        'status': 'ok',
        'data': {},
    }

    ratings['data']['resources'] = {}

    qs = [stat for stat in qs if stat['stage'] is None and stat['resource'] in resources]
    n_resources = len({stat['resource'] for stat in qs})
    for stat in qs:
        if stat['addition___rating_data'] and n_resources > 1:
            continue

        resource = resources[stat['resource']]
        default_info = dict(resource.info.get('ratings', {}).get('chartjs', {}))
        default_info['colors'] = resource.ratings
        resource_info = ratings['data']['resources'].setdefault(resource.host, default_info)
        resource_info.setdefault('data', [])

        if stat['addition___rating_data']:
            data = resource.plugin.Statistic.get_rating_history(stat['addition___rating_data'],
                                                                stat,
                                                                resource,
                                                                date_from=date_from,
                                                                date_to=date_to)
            if data:
                resource_info['data'].extend(data)
        else:
            stat.pop('addition___rating_data')
            stat['slug'] = slugify(stat['name'])
            division = stat.pop('division')
            problems = json.loads(stat.pop('problems') or '{}')
            if division and 'division' in problems:
                problems = problems['division'][division]
            stat['n_problems'] = len(problems)

            if stat['rating_change'] is not None and stat['old_rating'] is None:
                stat['old_rating'] = stat['new_rating'] - stat['rating_change']

            resource_info['data'].append(stat)

    resources_to_remove = [k for k, v in ratings['data']['resources'].items() if not v['data']]
    for k in resources_to_remove:
        ratings['data']['resources'].pop(k)

    dates = []
    for resource_info in ratings['data']['resources'].values():
        for stat in resource_info['data']:
            date = stat['date']
            dates.append(date)
            if stat['new_rating'] > resource_info.get('highest', {}).get('value', 0):
                resource_info['highest'] = {
                    'value': stat['new_rating'],
                    'timestamp': int(date.timestamp()),
                }
            if request.user.is_authenticated and request.user.coder:
                date = timezone.localtime(date, pytz.timezone(request.user.coder.timezone))
            date_format = stat.pop('date_format', '%b %-d, %Y')
            stat['when'] = date.strftime(date_format)
        resource_info['min'] = min([stat['new_rating'] for stat in resource_info['data']])
        resource_info['max'] = max([stat['new_rating'] for stat in resource_info['data']])
        resource_info['data'] = [resource_info['data']]

    ratings['data']['dates'] = list(sorted(set(dates)))
    return ratings


def ratings(request, username=None, key=None, host=None):
    ratings_data = get_ratings_data(
        request=request,
        username=username,
        key=key,
        host=host,
    )
    return JsonResponse(ratings_data)


@login_required
def settings(request, tab=None):
    coder = request.user.coder
    notification_form = NotificationForm(coder)
    if request.method == 'POST':
        if request.POST.get('action', None) == 'notification':
            notification_form = NotificationForm(coder, request.POST)
            if notification_form.is_valid():
                notification = notification_form.save(commit=False)
                if notification.method == django_settings.NOTIFICATION_CONF.TELEGRAM and not coder.chat:
                    return HttpResponseRedirect(django_settings.HTTPS_HOST_ + reverse('telegram:me'))
                notification.coder = coder
                notification.save()
                return HttpResponseRedirect(reverse('coder:settings') + '#notifications-tab')

    if request.GET.get('as_coder') and request.user.has_perm('as_coder'):
        coder = Coder.objects.get(user__username=request.GET['as_coder'])

    resources = Resource.objects.all()
    coder.filter_set.filter(resources=[], contest__isnull=True).delete()

    services = Service.objects.annotate(n_tokens=Count('token')).order_by('-n_tokens')

    selected_resource = request.GET.get('resource')
    selected_account = None
    if selected_resource:
        selected_resource = Resource.objects.filter(host=selected_resource).first()
        selected_account = request.GET.get('account')
        if selected_account:
            selected_account = Account.objects.filter(resource=selected_resource, key=selected_account).first()

    return render(
        request,
        "settings.html",
        {
            "resources": resources,
            "selected_resource": selected_resource,
            "selected_account": selected_account,
            "coder": coder,
            "tokens": {t.service_id: t for t in coder.token_set.all()},
            "services": services,
            "categories": coder.get_categories(),
            "notifications": coder.get_notifications(),
            "notification_form": notification_form,
            "modules": Module.objects.select_related('resource').order_by('resource__id').all(),
            "ace_calendars": django_settings.ACE_CALENDARS_,
            "custom_countries": django_settings.CUSTOM_COUNTRIES_,
            "tab": tab,
        },
    )


@login_required
@require_http_methods(['POST'])
def change(request):
    name = request.POST.get("name", None)
    value = request.POST.get("value", None)

    if value in ["true", "false"]:
        value = "1" if value == "true" else "0"

    user = request.user
    coder = user.coder

    if coder.id != int(request.POST.get("pk", -1)):
        return HttpResponseBadRequest("invalid pk")
    if name == "theme":
        if value not in django_settings.THEMES_:
            return HttpResponseBadRequest("invalid theme name")
        if value == 'default':
            coder.settings.pop('theme')
        else:
            coder.settings['theme'] = value
        coder.save()
    elif name == "timezone":
        if value not in (tz["name"] for tz in get_timezones()):
            return HttpResponseBadRequest("invalid timezone name")
        coder.timezone = value
        coder.save()
    elif name == "check-timezone":
        if value not in ["0", "1", ]:
            return HttpResponseBadRequest("invalid check timezone value")
        coder.settings["check_timezone"] = int(value)
        coder.save()
    elif name == "time-format":
        try:
            format_time(timezone.now(), value)
        except Exception as e:
            return HttpResponseBadRequest(e)
        coder.settings["time_format"] = value
        if value == "":
            coder.settings.pop("time_format")
        coder.save()
    elif name == "add-to-calendar":
        if value not in django_settings.ACE_CALENDARS_.keys():
            return HttpResponseBadRequest("invalid add-to-calendar value")
        coder.settings["add_to_calendar"] = value
        coder.save()
    elif name == "share-to-category":
        categories = [k for k, v in coder.get_notifications()]
        if value != 'disable' and value not in categories:
            return HttpResponseBadRequest("invalid share-to-category value")
        coder.settings["share_to_category"] = value
        coder.save()
    elif name == "view-mode":
        if value in ["0", "1"]:
            value = "list" if value == "1" else "calendar"
        if value not in ["list", "calendar", ]:
            return HttpResponseBadRequest("invalid view mode")
        coder.settings["view_mode"] = value
        coder.save()
    elif name in ["hide-contest", "all-standings", "open-new-tab", "group-in-list", "calendar-filter-long"]:
        if value not in ["0", "1", ]:
            return HttpResponseBadRequest(f"invalid {name} value")
        key = name.replace('-', '_')
        coder.settings[key] = int(value)
        coder.save()
    elif name == "email":
        if value not in (token.email for token in coder.token_set.all()):
            return HttpResponseBadRequest("invalid email")
        user.email = value
        user.save()
    elif name == "country":
        coder.country = value
        coder.save()
    elif name == "custom-countries":
        country = request.POST.get("country", None)
        if country not in django_settings.CUSTOM_COUNTRIES_:
            return HttpResponseBadRequest(f"invalid custom country '{country}'")
        if value not in django_settings.CUSTOM_COUNTRIES_[country]:
            return HttpResponseBadRequest(f"invalid custom value '{value}' for country '{country}'")

        with transaction.atomic():
            coder.settings.setdefault('custom_countries', {})[country] = value
            coder.save()

            for account in coder.account_set.prefetch_related('coders'):
                update_account_by_coders(account)
    elif name == "filter":
        try:
            field = "Filter id"
            id_ = int(request.POST.get("value[id]", -1))
            filter_ = Filter.objects.get(pk=id_, coder=coder)

            filter_.name = request.POST.get("value[name]", "").strip().replace("'", "") or None

            field = "Duration"
            duration_from = request.POST.get("value[duration][from]", None)
            filter_.duration_from = int(duration_from) if duration_from and duration_from != "NaN" else None

            duration_to = request.POST.get("value[duration][to]", None)
            filter_.duration_to = int(duration_to) if duration_to and duration_to != "NaN" else None

            if filter_.duration_from and filter_.duration_to and filter_.duration_from > filter_.duration_to:
                raise Exception("{from} should be less or equal {to}")

            field = "Regex"
            regex = request.POST.get("value[regex]", None)
            if regex:
                re.compile(regex)
                Contest.objects.filter(title__regex=regex).first()
            filter_.regex = regex if regex else None

            field = "Inverse regex"
            filter_.inverse_regex = request.POST.get("value[inverse_regex]", "false") == "true"

            if filter_.inverse_regex and not filter_.regex:
                raise Exception("inverse set but regex is empty")

            field = "To show"
            filter_.to_show = request.POST.get("value[to_show]", "false") == "true"

            field = "Resources"
            filter_.resources = list(map(int, request.POST.getlist("value[resources][]", [])))
            if Resource.objects.filter(pk__in=filter_.resources).count() != len(filter_.resources):
                raise Exception("invalid id")

            field = "Contest"
            contest_id = request.POST.get("value[contest]", None)
            if contest_id:
                filter_.contest = Contest.objects.get(pk=contest_id)
            else:
                filter_.contest = None

            field = "Resources and contest"
            if not filter_.resources and not filter_.contest:
                raise Exception("empty")

            categories = [c['id'] for c in coder.get_categories()]
            field = "Categories"
            filter_.categories = request.POST.getlist("value[categories][]", [])
            if not all([c in categories for c in filter_.categories]):
                raise Exception("invalid value(s)")
            if len(filter_.categories) == 0:
                raise Exception("empty")

            filter_.save()
        except Exception as e:
            return HttpResponseBadRequest("%s: %s" % (field, e))
    elif name == "add-filter":
        if coder.filter_set.count() >= 50:
            return HttpResponseBadRequest("reached the limit number of filters")
        filter_ = Filter.objects.create(coder=coder)
        return HttpResponse(json.dumps(filter_.dict()), content_type="application/json")
    elif name == "delete-filter":
        try:
            id_ = int(request.POST.get("id", -1))
            filter_ = Filter.objects.get(pk=id_, coder=coder)
            filter_.delete()
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name in ("delete-notification", "reset-notification", ):
        try:
            id_ = int(request.POST.get("id", -1))
            n = Notification.objects.get(pk=id_, coder=coder)
            if name == "delete-notification":
                n.delete()
            elif name == "reset-notification":
                n.last_time = timezone.now()
                n.save()
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "first-name":
        if not value:
            return HttpResponseBadRequest("empty first name")
        user.first_name = value
        user.save()
    elif name == "last-name":
        if not value:
            return HttpResponseBadRequest("empty last name")
        user.last_name = value
        user.save()
    elif name == "first-name-native":
        if not value:
            return HttpResponseBadRequest("empty first name in native language")
        coder.first_name_native = value
        coder.save()
    elif name == "last-name-native":
        if not value:
            return HttpResponseBadRequest("empty last name in native language")
        coder.last_name_native = value
        coder.save()
    elif name == "add-account":
        if not value:
            return HttpResponseBadRequest("empty account value")
        try:
            resource_id = int(request.POST.get("resource"))
            resource = Resource.objects.get(pk=resource_id)
            account = Account.objects.get(resource=resource, key=value)
            if account.coders.filter(pk=coder.id).first():
                raise Exception('Account is already connect to this coder')

            module = Module.objects.filter(resource=resource).first()
            if not module or not module.multi_account_allowed:
                if coder.account_set.filter(resource=resource).exists():
                    raise Exception('Allow only one account for this resource')
                if account.coders.count():
                    raise Exception('Account is already connect')

            account.coders.add(coder)
            account.save()
            return HttpResponse(json.dumps(account.dict()), content_type="application/json")
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "delete-account":
        if not value:
            return HttpResponseBadRequest("empty account value")
        try:
            host = request.POST.get("resource")
            account = Account.objects.get(resource__host=host, key=value)
            account.coders.remove(coder)
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "pre-delete-user":
        class RollbackException(Exception):
            pass
        try:
            with transaction.atomic():
                _, delete_info = user.delete()
                delete_info = [(k, v) for k, v in delete_info.items() if v]
                delete_info.sort(key=lambda d: d[1], reverse=True)
                raise RollbackException()
        except RollbackException:
            pass
        delete_info = '\n'.join(f'{k}: {v}' for k, v in delete_info)
        return JsonResponse({'status': 'ok', 'data': delete_info})
    elif name == "delete-user":
        username = request.POST.get("username")
        if username != user.username:
            return HttpResponseBadRequest(f"invalid username: found '{username}', expected '{user.username}'")
        user.delete()
    else:
        return HttpResponseBadRequest("unknown query")

    return HttpResponse("accepted")


def search(request, **kwargs):
    query = request.GET.get('query', None)
    if not query or not isinstance(query, str):
        return HttpResponseBadRequest('invalid query')

    count = int(request.GET.get('count', 10))
    page = int(request.GET.get('page', 1))
    if query == 'themes':
        ret = {}
        for t in django_settings.THEMES_:
            ret[t] = t.title()
        return JsonResponse(ret)
    elif query == 'timezones':
        ret = {}
        for tz in get_timezones():
            ret[tz["name"]] = f'{tz["name"]} {tz["repr"]}'
        return JsonResponse(ret)
    elif query == 'resources':
        qs = Resource.objects.all()
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'host'))
        qs = qs.order_by('-n_accounts')

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.host, 'icon': r.icon} for r in qs]
    elif query == 'resources-for-add-account' and request.user.is_authenticated:
        coder = request.user.coder
        coder_accounts = coder.account_set.filter(resource=OuterRef('pk'))

        qs = Resource.objects \
            .annotate(has_coder_account=Exists(coder_accounts)) \
            .annotate(has_multi=F('module__multi_account_allowed')) \
            .annotate(disabled=Case(
                When(module__isnull=True, then=Value(True)),
                When(has_coder_account=True, has_multi=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ))
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'host'))
        qs = qs.order_by('disabled', 'pk')

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [
            {
                'id': r.id,
                'text': r.host,
                'disabled': r.disabled,
            }
            for r in qs
        ]
    elif query == 'accounts-for-add-account' and request.user.is_authenticated:
        coder = request.user.coder

        qs = Account.objects.all()
        resource = request.GET.get('resource')
        if resource:
            qs = qs.filter(resource__id=int(resource))
        else:
            qs = qs.select_related('resource')
        if 'user' in request.GET:
            re_search = request.GET.get('user')
            qs = qs.filter(get_iregex_filter(re_search, 'key', 'name'))
            search_striped = re_search.rstrip('$').lstrip('^')
            qs = qs.annotate(match=Case(
                When(Q(key__iexact=search_striped) | Q(name__iexact=search_striped), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ))
        else:
            qs = qs.annotate(match=Value(False, output_field=BooleanField()))

        qs = qs.annotate(has_multi=F('resource__module__multi_account_allowed'))

        qs = qs.annotate(disabled=Case(
            When(coders=coder, then=Value(True)),
            When(coders__isnull=False, has_multi=False, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ))

        qs = qs.order_by('disabled', '-match')

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = []
        for r in qs:
            fields = {
                'id': r.key,
                'text': f'{r.key} - {r.name}' if r.name and r.key.find(r.name) == -1 else r.key,
                'disabled': r.disabled,
            }
            if not resource:
                fields['text'] += f', {r.resource.host}'
                fields['resource'] = {'id': r.resource.pk, 'text': r.resource.host}
            ret.append(fields)
    elif query == 'organization':
        qs = Organization.objects.all()

        name = request.GET.get('name')
        if name:
            qs = qs.filter(Q(name__icontains=name) | Q(name_ru__icontains=name) | Q(abbreviation__icontains=name))

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': o.name, 'text': o.name} for o in qs]
    elif query == 'team':
        qs = Team.objects.all()

        name = request.GET.get('name')
        if name:
            qs = qs.filter(name__icontains=name)

        event = kwargs.get('event')
        if event:
            qs = qs.filter(event=event)
        qs = qs.annotate(disabled=Case(
            When(status=TeamStatus.NEW, then=Value(False)),
            default=Value(True),
            output_field=BooleanField())
        ).order_by('disabled', '-modified')

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.name, 'disabled': r.disabled} for r in qs]
    elif query == 'country':
        qs = list(countries)
        name = request.GET.get('name')
        if name:
            name = name.lower()
            qs = [(c, n) for c, n in countries if name in n.lower()]
        total = len(qs)
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c, 'text': n} for c, n in qs]
    elif query == 'notpast':
        title = request.GET.get('title')
        qs = Contest.objects.filter(title__iregex=verify_regex(title), end_time__gte=timezone.now())
        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c.id, 'text': c.title} for c in qs]
    elif query == 'field-to-select':
        contest = get_object_or_404(Contest, pk=request.GET.get('cid'))
        text = request.GET.get('text')
        field = request.GET.get('field')
        assert '__' not in field

        if field == 'languages':
            qs = contest.info.get('languages', [])
            qs = ['any'] + [q for q in qs if not text or text.lower() in q.lower()]
            total = len(qs)
        elif field == 'rating':
            qs = ['rated', 'unrated']
            total = len(qs)
        else:
            field = f'addition__{field}'
            qs = contest.statistics_set
            if text:
                qs = qs.filter(**{f'{field}__icontains': text})
            qs = qs.distinct(field).values_list(field, flat=True)
            total = qs.count()

        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': f, 'text': f} for f in qs]
    elif query == 'coders':
        qs = Coder.objects.all()

        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'username'))

        order = ['-n_accounts', 'pk']
        if request.user.is_authenticated:
            qs = qs.annotate(iam=Case(
                When(pk=request.user.coder.pk, then=Value(0)),
                default=Value(1),
                output_field=IntegerField()
            ))
            order.insert(0, 'iam')
        qs = qs.order_by(*order)

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.username} for r in qs]
    elif query == 'accounts':
        qs = Account.objects.all()
        if request.GET.get('resource'):
            qs = qs.filter(resource_id=int(request.GET.get('resource')))

        order = ['-n_contests', 'pk']
        if 'regex' in request.GET:
            re_search = request.GET['regex']
            qs = qs.filter(get_iregex_filter(re_search, 'key', 'name'))
            search_striped = re_search.rstrip('$').lstrip('^')
            qs = qs.annotate(match=Case(
                When(Q(key__iexact=search_striped) | Q(name__iexact=search_striped), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ))
            order.insert(0, '-match')
        qs = qs.select_related('resource')
        qs = qs.order_by(*order)

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [
            {
                'id': r.id,
                'text': f'{r.key}, {r.name}, {r.resource.host}' if r.name else f'{r.key}, {r.resource.host}'
            } for r in qs
        ]
    else:
        return HttpResponseBadRequest('invalid query')

    result = {
        'items': ret,
        'more': page * count <= total,
    }

    return HttpResponse(json.dumps(result, ensure_ascii=False), content_type="application/json")


@login_required
@require_http_methods(['POST'])
def get_api_key(request):
    if hasattr(request.user, 'api_key') and request.user.api_key is not None:
        api_key = request.user.api_key
    else:
        api_key = ApiKey.objects.create(user=request.user)
    return HttpResponse(api_key.key)


@login_required
@require_http_methods(['DELETE'])
def remove_api_key(request):
    ret = ApiKey.objects.filter(user=request.user).delete()
    return HttpResponse(str(ret))


def unsubscribe(request):
    pk = request.GET.get('pk')
    secret = request.GET.get('secret')
    notification = get_object_or_404(Notification, pk=pk, secret=secret)
    if 'unsubscribe' in request.POST:
        if request.POST.get('unsubscribe'):
            notification.delete()
        return HttpResponse('ok')
    return render(request, 'unsubscribe.html', context={'notification': notification})


@login_required
def party_action(request, secret_key, action):
    party = get_object_or_404(Party, secret_key=secret_key)
    coder = request.user.coder
    if coder.party_set.filter(pk=party.id).exists():
        if action == 'join':
            messages.warning(request, 'You are already in %s.' % party.name)
        elif action == 'leave':
            coder.party_set.remove(party)
            messages.success(request, 'You leave party %s.' % party.name)
    else:
        if action == 'join':
            party.coders.add(coder)
            messages.success(request, 'You join to %s.' % party.name)
        elif action == 'leave':
            messages.warning(request, 'You are not there in %s.' % party.name)
    return HttpResponseRedirect(reverse('coder:party', args=[party.slug]))


def party(request, slug, tab='ranking'):
    party = get_object_or_404(Party.objects.for_user(request.user), slug=slug)

    party_contests = Contest.objects \
        .filter(rating__party=party) \
        .annotate(has_statistics=Exists('statistics')) \
        .order_by('-end_time')

    filt = Q(rating__party=party, statistics__account__coders=OuterRef('pk'))
    coders = party.coders \
        .annotate(n_participations=SubqueryCount('account__resource__contest', filter=filt)) \
        .order_by('-n_participations') \
        .select_related('user')
    set_coders = set(coders)

    if request.user.is_authenticated:
        ignore_filters = request.user.coder.filter_set.filter(categories__contains=['calendar']).order_by('created')
        ignore_filters = list(ignore_filters.values('id', 'name'))
    else:
        ignore_filters = []
    ignore_filters.append({'id': 0, 'name': 'disable long'})

    results = []
    total = {}

    contests = Contest.objects.filter(rating__party=party)
    future = contests.filter(end_time__gt=timezone.now()).order_by('start_time')

    statistics = Statistics.objects.filter(
        account__coders__in=party.coders.all(),
        contest__in=party_contests.filter(start_time__lt=timezone.now()),
        contest__end_time__lt=timezone.now(),
    ) \
        .order_by('-contest__end_time') \
        .select_related('contest', 'account') \
        .prefetch_related('account__coders', 'account__coders__user')

    contests_standings = collections.OrderedDict(
        (c, {}) for c in contests.filter(end_time__lt=timezone.now()).order_by('-end_time')
    )
    for statistic in statistics:
        contest = statistic.contest
        for coder in statistic.account.coders.all():
            if coder in set_coders:
                standings = contests_standings[contest].setdefault(statistic.addition.get('division', '__none__'), [])
                standings.append({
                    'solving': statistic.solving,
                    'upsolving': statistic.upsolving,
                    'stat': statistic,
                    'coder': coder,
                })

    for contest, divisions in contests_standings.items():
        standings = []
        fields = collections.OrderedDict()
        if len(divisions) > 1 or '__none__' not in divisions:
            fields['division'] = ('Div', 'division', 'Division')
        for division, statistics in divisions.items():
            if statistics:
                max_solving = max([s['solving'] for s in statistics]) or 1
                max_total = max([s['solving'] + s['upsolving'] for s in statistics]) or 1

                for s in statistics:
                    solving = s['solving']
                    upsolving = s['upsolving']
                    s['score'] = 4. * (solving + upsolving) / max_total + 1. * solving / max_solving
                    s['interpretation'] = f'4 * ({solving} + {upsolving}) / {max_total} + {solving} / {max_solving}'
                    s['division'] = s['stat'].addition.get('division', '').replace('_', ' ')

                max_score = max([s['score'] for s in statistics]) or 1
                for s in statistics:
                    s['score'] = 100. * s['score'] / max_score
                    s['interpretation'] = [f'100 * ({s["interpretation"]}) / {max_score}']

                for s in statistics:
                    coder = s['coder']
                    d = total.setdefault(coder.id, {})
                    d['score'] = s['score'] + d.get('score', 0)
                    d['coder'] = coder
                    d['num'] = d.setdefault('num', 0) + 1
                    d['avg'] = f"{(d['score'] / d['num']):.2f}"

                    d, s = d.setdefault('stat', {}), s['stat']

                    solved = s.addition.get('solved', {})
                    d['solving'] = solved.get('solving', s.solving) + d.get('solving', 0)
                    d['upsolving'] = solved.get('upsolving', s.upsolving) + d.get('upsolving', 0)

                standings.extend(statistics)

        standings.sort(key=lambda s: s['score'], reverse=True)

        results.append({
            'contest': contest,
            'standings': standings,
            'fields': list(fields.values()),
        })

    total = sorted(list(total.values()), key=lambda d: d['score'], reverse=True)
    results.insert(0, {
        'standings': total,
        'fields': [('Num', 'num', 'Number contests'), ('Avg', 'avg', 'Average score')],
    })

    for result in results:
        place = 0
        prev = None
        for i, s in enumerate(result['standings']):
            if prev != s['score']:
                prev = s['score']
                place = i + 1
            s['place'] = place

    return render(
        request,
        'party.html',
        {
            'ignore_filters': [],
            'fixed_ignore_filters': ignore_filters,
            'timezone': get_timezone(request),
            'future': future,
            'party': party,
            'party_contests': party_contests,
            'results': results,
            'coders': coders,
            'tab': 'ranking' if tab is None else tab,
        },
    )


def parties(request):
    parties = Party.objects.for_user(request.user).order_by('-created')
    parties = parties.prefetch_related('coders', 'rating_set')
    return render(request, 'parties.html', {'parties': parties})


def party_contests(request, slug):
    party = get_object_or_404(Party.objects.for_user(request.user), slug=slug)

    action = request.GET.get("action")
    if action is not None:
        if (
            action == "party-contest-toggle"
            and request.user.is_authenticated
            and party.has_permission_toggle_contests(request.user.coder)
        ):
            contest = get_object_or_404(Contest, pk=request.GET.get("pk"))
            rating, created = Rating.objects.get_or_create(contest=contest, party=party)
            if not created:
                rating.delete()
                return HttpResponse("deleted")
            return HttpResponse("created")
        return HttpResponseBadRequest("fail")

    return main(request, party=party)
