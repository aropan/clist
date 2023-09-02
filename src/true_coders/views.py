import collections
import functools
import json
import logging
import operator
import re
from collections import Counter
from datetime import datetime, timedelta

import humanize
import pytz
from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import (BigIntegerField, BooleanField, Case, Count, F, FloatField, IntegerField, JSONField, Max,
                              OuterRef, Prefetch, Q, Subquery, Value, When)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_http_methods
from django_countries import countries
from django_ratelimit.core import get_usage
from django_rq import job
from el_pagination.decorators import page_template, page_templates
from sql_util.utils import Exists, SubqueryCount, SubqueryMax, SubquerySum
from tastypie.models import ApiKey

from clist.models import Contest, ContestSeries, ProblemTag, Resource
from clist.templatetags.extras import (asfloat, format_time, get_timezones, has_update_statistics_permission,
                                       query_transform, quote_url, relative_url)
from clist.templatetags.extras import slug as slugify
from clist.templatetags.extras import toint
from clist.views import get_timeformat, get_timezone, main
from events.models import Team, TeamStatus
from favorites.models import Activity
from my_oauth.models import Service
from notes.models import Note
from notification.forms import Notification, NotificationForm
from notification.models import Calendar, NotificationMessage, Subscription
from pyclist.decorators import context_pagination
from pyclist.middleware import RedirectException
from ranking.models import (Account, AccountVerification, Module, Rating, Statistics, VerifiedAccount,
                            update_account_by_coders)
from tg.models import Chat
from true_coders.models import Coder, CoderList, Filter, ListValue, Organization, Party
from utils.chart import make_chart
from utils.json_field import JSONF
from utils.regex import get_iregex_filter, verify_regex

logger = logging.getLogger(__name__)


def get_medals_for_profile_context(statistics):
    qs = statistics \
        .select_related('contest') \
        .filter(addition__medal__isnull=False) \
        .order_by('-contest__end_time')
    resource_medals = {}
    account_medals = {}
    for stat in qs:
        if not stat.contest.related_id:
            resource_medals.setdefault(stat.contest.resource_id, []).append(stat)
        account_medals.setdefault(stat.account_id, []).append(stat)

    def group_medals(medals_dict, n_fixed=3):
        ret = {}
        for k, medals in medals_dict.items():
            grouped_medals = medals[:n_fixed]
            medals = [(stat.addition['medal'].lower(), stat) for stat in medals[n_fixed:]]
            while medals:
                next_medal, _ = medals[0]
                filtered = [stat for (medal, stat) in medals if next_medal == medal]
                if len(filtered) == 1:
                    grouped_medals.append(filtered[0])
                else:
                    grouped_medals.append({'medal': next_medal, 'medals': filtered})
                medals = [(medal, stat) for (medal, stat) in medals if next_medal != medal]
            ret[k] = grouped_medals
        return ret

    return {
        'resource_medals': group_medals(resource_medals),
        'account_medals': group_medals(account_medals),
    }


def get_profile_context(request, statistics, writers, resources):
    context = {}
    context.update(get_medals_for_profile_context(statistics))

    statistics = statistics \
        .select_related('contest', 'contest__resource', 'account') \
        .order_by('-contest__end_time')

    search = request.GET.get('search')
    filters = {}
    if search:
        filt = get_iregex_filter(
            search, 'contest__title', 'contest__resource__host',
            mapping={
                'writer': {'fields': ['contest__info__writers__contains']},
                'contest': {'fields': ['contest__title__iregex']},
                'resource': {'fields': ['contest__resource__host']},
                'account': {'fields': ['account__key']},
                'type': {'fields': ['contest__kind']},
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
        if not filter_resources:
            field = 'contest__resource__host'
            filter_resources = list(statistics.order_by(field).distinct(field).values_list(field, flat=True))

        if filter_resources:
            conditions = [Q(host=host) for host in filter_resources]
            resources = resources.filter(functools.reduce(operator.ior, conditions))

    kinds_resources = collections.defaultdict(dict)
    rated_stats = statistics.filter(
        Q(addition__new_rating__isnull=False) |
        Q(addition__rating_change__isnull=False) |
        Q(addition___rating_data__isnull=False)
    )
    for stat in rated_stats.order_by().distinct('contest__resource__host', 'contest__kind'):
        resource = stat.contest.resource
        kind = stat.contest.kind
        kind = None if resource.is_major_kind(kind) else kind
        kinds_resources[resource.pk][kind] = {
            'host': resource.host,
            'pk': resource.pk,
            'icon': resource.icon,
            'kind': kind,
        }
    history_resources = list()
    for resource in resources.filter(has_rating_history=True):
        history_resources.extend(kinds_resources[resource.pk].values())

    resources = list(resources)
    search_resource = resources[0] if len(resources) == 1 else None

    if search_resource:
        writers = writers.filter(resource__host=search_resource)
    writers = writers.order_by('-end_time')
    writers = writers.annotate(has_statistics=Exists('statistics'))

    if not search_resource:
        statistics = statistics.filter(contest__invisible=False)

    # custom fields
    custom_fields = None
    if search_resource:
        stat = statistics.filter(contest__stage__isnull=True).first()
        if stat:
            options = []
            for k in stat.addition.keys():
                if Statistics.is_special_addition_field(k):
                    continue
                options.append(k)
            options.sort()
            fields = request.GET.getlist('field')
            custom_fields = {
                'values': [v for v in fields if v and v in options],
                'options': options,
                'noajax': True,
                'nogroupby': True,
                'nourl': True,
            }

    context.update({
        'statistics': statistics,
        'writers': writers,
        'resources': list(resources),
        'two_columns': len(resources) > 1,
        'history_resources': history_resources,
        'show_history_ratings': not filters,
        'search_resource': search_resource,
        'timezone': get_timezone(request),
        'timeformat': get_timeformat(request),
        'custom_fields': custom_fields,
    })

    qs = statistics.annotate(date=F('contest__start_time'))
    qs = qs.filter(place__isnull=False).order_by()
    contests_chart = make_chart(qs, field='date', n_bins=21, norm_value=timedelta(days=1))
    context['contests_chart'] = contests_chart

    return context


@login_required
def my_profile(request):
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
        filt = get_iregex_filter(
            search,
            'username',
            'first_name_native',
            'last_name_native',
            'middle_name_native',
            'user__first_name',
            'user__last_name',
            logger=request.logger,
        )
        coders = coders.filter(filt)

    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        coders = coders.annotate(filter_country=Exists('account', filter=Q(account__country__in=countries)))
        coders = coders.filter(Q(country__in=countries) | Q(filter_country=True))
        params['countries'] = countries

    virtual = request.GET.get('virtual') or 'hide'
    if virtual == 'hide':
        coders = coders.filter(is_virtual=False)
    elif virtual == 'only':
        coders = coders.filter(is_virtual=True)
    virtual_field = {
        'values': [virtual],
        'options': ['hide', 'show', 'only'],
        'nomultiply': True,
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
    }

    chat_fields = None
    view_coder_chat = None
    if request.user.is_authenticated:
        coder = request.user.coder
        chats = coder.chats.all()
        if chats:
            options_values = {c.chat_id: c.title for c in chats}
            chat_fields = {
                'values': [v for v in request.GET.getlist('chat') if v and v in options_values],
                'options': options_values,
                'noajax': True,
                'nogroupby': True,
                'nourl': True,
            }

            filt = Q()
            for value in chat_fields['values']:
                chat = Chat.objects.filter(chat_id=value, is_group=True).first()
                filt |= Q(pk__in=chat.coders.all())
            coders = coders.filter(filt)

            if request.user.has_perm('true_coders.view_coder_chat') and chat_fields['values']:
                view_coder_chat = True
                coders = coders.prefetch_related(
                    Prefetch(
                        'chat_set',
                        queryset=Chat.objects.filter(is_group=False),
                        to_attr='non_group_chats',
                    )
                )

    resources = request.GET.getlist('resource')
    if resources:
        resources = [r for r in resources if r]
        resources = list(Resource.objects.filter(pk__in=resources))
        for r in resources:
            field = r.info.get('ratings', {}).get('chartjs', {}).get('coloring_field')
            if field:
                field = Cast(KeyTextTransform(field, 'account__info'), IntegerField())
                coders = coders.annotate(**{f'{r.pk}_coloring_rating': SubqueryMax(field, filter=Q(resource=r))})
            coders = coders.annotate(**{f'{r.pk}_rating': SubqueryMax('account__rating', filter=Q(resource=r))})
            coders = coders.annotate(**{f'{r.pk}_n_contests': SubquerySum('account__n_contests', filter=Q(resource=r))})
        params['resources'] = resources

    custom_fields = None
    if len(resources) == 1:
        resource = resources[0]
        options = list(resource.accounts_fields.get('types', {}).keys())
        custom_fields = {
            'values': [v for v in request.GET.getlist('field') if v and v in options],
            'options': options,
            'noajax': True,
            'nogroupby': True,
            'nourl': True,
        }
        coders = coders.prefetch_related(
            Prefetch(
                'account_set',
                queryset=resource.account_set.order_by('-n_contests'),
                to_attr='resource_account',
            )
        )

    # ordering
    orderby = request.GET.get('sort_column')
    if orderby in ['username', 'global_rating', 'created', 'n_accounts', 'n_contests']:
        pass
    elif orderby and orderby.startswith('resource_'):
        _, pk = orderby.split('_')
        if pk.isdigit() and int(pk) in [r.pk for r in params.get('resources', [])]:
            orderby = [f'{pk}_rating', f'{pk}_n_contests']
        else:
            orderby = []
    elif orderby:
        request.logger.error(f'Not found `{orderby}` column for sorting')
        orderby = []
    orderby = orderby if not orderby or isinstance(orderby, list) else [orderby]
    order = request.GET.get('sort_order')
    if order in ['asc', 'desc']:
        orderby = [getattr(F(o), order)(nulls_last=True) for o in orderby]
    elif order:
        request.logger.error(f'Not found `{order}` order for sorting')
    main_field = 'global_rating' if django_settings.ENABLE_GLOBAL_RATING_ else 'n_contests'
    orderby = orderby or [F(main_field).desc(nulls_last=True), '-created']
    coders = coders.order_by(*orderby)

    context = {
        'coders': coders,
        'params': params,
        'virtual_field': virtual_field,
        'chat_fields': chat_fields,
        'custom_fields': custom_fields,
        'view_coder_chat': view_coder_chat,
    }
    return template, context


@page_templates((
    ('profile_contests_paging.html', 'contest_page'),
    ('profile_writers_paging.html', 'writers_page'),
))
def profile(request, username, template='profile_coder.html', extra_context=None):
    coder = get_object_or_404(Coder, username=username)
    data = _get_data_mixed_profile(request, [username])
    context = get_profile_context(request, data['statistics'], data['writers'], data['resources'])
    context['coder'] = coder
    if coder.has_global_rating:
        context['history_resources'].insert(0, dict(django_settings.CLIST_RESOURCE_DICT_))

    if request.user.is_authenticated and request.user.coder == coder:
        context['without_findme'] = True
        context['this_is_me'] = True

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


def account_context(request, key, host):
    accounts = Account.objects.select_related('resource').prefetch_related('coders')
    resource = get_object_or_404(Resource, host=host)
    account = get_object_or_404(accounts, key=key, resource=resource)

    context = {
        'account': account,
        'without_accounts': True,
    }

    add_account_button = False
    verified = bool(VerifiedAccount.objects.filter(account=account).exists())
    need_verify = True
    if request.user.is_authenticated:
        coder = request.user.coder
        need_verify = not bool(VerifiedAccount.objects.filter(coder=coder, account=account).exists())
        coder_account = coder.account_set.filter(resource=account.resource).first()
        if need_verify and not account.resource.with_multi_account() and coder_account and account != coder_account:
            need_verify = False
        if account.resource.with_multi_account() or coder_account:
            add_account_button = True
    else:
        coder = None
        add_account_button = True
    context['add_account_button'] = add_account_button
    context['verified_account'] = verified
    context['need_verify'] = need_verify

    wait_rating = account.resource.info.get('statistics', {}).get('wait_rating', {})
    context['show_add_account_message'] = (
        wait_rating.get('has_coder')
        and account.resource.has_rating_history
        and not account.coders.all()
        and (
            account.last_activity is None
            or '_rating_time' not in account.info
            or (
                account.last_activity
                - make_aware(datetime.fromtimestamp(account.info['_rating_time']))
                > timedelta(days=wait_rating.get('days', 7))
            )
        )
    )

    if request.user.is_authenticated and coder in account.coders.all():
        context['without_findme'] = True
        context['this_is_me'] = True
        context['add_account_button'] = False
    return context


@page_templates((
    ('profile_contests_paging.html', 'contest_page'),
    ('profile_writers_paging.html', 'writers_page'),
))
def account(request, key, host, template='profile_account.html', extra_context=None):
    context = account_context(request, key, host)
    account = context['account']

    data = _get_data_mixed_profile(request, [account.resource.host + ':' + account.key])
    profile_context = get_profile_context(request, data['statistics'], data['writers'], data['resources'])
    context.update(profile_context)

    if extra_context is not None:
        context.update(extra_context)

    return render(request, template, context)


@login_required
def account_verification(request, key, host, template='account_verification.html'):
    context = account_context(request, key, host)
    account = context['account']
    resource = account.resource
    coder = request.user.coder
    this_is_me = bool(context.get('this_is_me'))
    is_single_account = resource.with_single_account() or account.rating is not None
    if not request.user.has_perm('true_coders.force_account_verification'):
        if not resource.has_account_verification:
            return HttpResponseBadRequest(f'Account verification is not supported for {resource.host} resource')
        if not context.get('need_verify'):
            return HttpResponseBadRequest('Account already verified')
        if not this_is_me and is_single_account and coder.account_set.filter(resource=resource).exists():
            return HttpResponseBadRequest('Allow only one account for resource')
    verification, created = AccountVerification.objects.get_or_create(coder=coder, account=account)
    context['verification'] = verification

    action = request.POST.get('action')
    if action == 'verify':
        usage = get_usage(request, group='verify-account', key='user', rate='1/m', increment=True)
        if usage['should_limit']:
            delta = timedelta(seconds=usage['time_left'])
            return HttpResponseBadRequest(f'Try again in {humanize.naturaldelta(delta)}', status=429)
        try:
            info = resource.plugin.Statistic.get_account_fields(account)
            verified = False
            verification_text = verification.text()
            for field, value in info.items():
                if isinstance(value, str) and verification_text in value:
                    verified = True
                    break
            if not verified:
                return HttpResponseBadRequest('Verification text not found')
            with transaction.atomic():
                if not this_is_me:
                    if is_single_account:
                        account.coders.clear()
                    coder.add_account(account)
                VerifiedAccount.objects.get_or_create(coder=coder, account=account)
            return HttpResponse('ok')
        except Exception as e:
            logger.error(f'Error while verification: {e}')
            return HttpResponseBadRequest('Unknown error while verification')

    return render(request, template, context)


def _get_data_mixed_profile(request, query):
    statistics_filter = Q()
    writers_filter = Q()
    accounts_filter = Q()
    profiles = []

    if not isinstance(query, (list, tuple)):
        query = query.split(',')

    if len(query) > 20:
        query = query[:20]
        request.logger.warning('The query is truncated to the first 20 records')

    if request.user.is_authenticated:
        coder_list = request.POST.get('list')
        if coder_list:
            coder = request.user.coder
            coder_list = get_object_or_404(CoderList, owner=coder, uuid=coder_list)
            url = reverse('coder:list', args=(str(coder_list.uuid),))
            request.session['view_list_request_post'] = {
                'raw': ','.join(query),
                'uuid': str(coder_list.uuid),
            }
            raise RedirectException(redirect(url))

    n_accounts = 0
    for v in query:
        n_accounts += ':' in v

    account_prefilter = Q()
    n_coder = 0
    for v in query:
        if ':' in v:
            host, key = v.split(':', 1)
            resource = Resource.objects.filter(Q(host=host) | Q(short_host=host)).first()
            if not resource:
                continue
            account_prefilter |= Q(key=key, resource=resource)
        elif n_coder:
            request.logger.warning(f'Coder {v} was skipped: only the first one is used')
        else:
            coder = Coder.objects.filter(username=v).first()
            if coder:
                if n_accounts == 0:
                    statistics_filter |= Q(account__coders=coder)
                    writers_filter |= Q(writers__coders=coder)
                    accounts_filter |= Q(coders=coder)
                else:
                    accounts = list(coder.account_set.all())
                    statistics_filter |= Q(account__in=accounts)
                    writers_filter |= Q(writers__in=accounts)
                    accounts_filter |= Q(pk__in={a.pk for a in accounts})
                profiles.append(coder)
                n_coder += 1

    if account_prefilter:
        for account in Account.objects.filter(account_prefilter):
            statistics_filter |= Q(account=account)
            writers_filter |= Q(writers=account)
            accounts_filter |= Q(pk=account.pk)
            profiles.append(account)

    if not profiles:
        statistics = Statistics.objects.none()
        writers = Contest.objects.none()
        resources = Resource.objects.none()
    else:
        statistics = Statistics.objects.filter(statistics_filter)
        writers = Contest.objects.filter(writers_filter).select_related('resource').order_by('-end_time')
        accounts = Account.objects.filter(accounts_filter).order_by('-n_contests')
        if n_coder:
            accounts = accounts.annotate(verified=Exists('verified_accounts', filter=Q(coder=coder)))

        resources = Resource.objects \
            .prefetch_related(Prefetch(
                'account_set',
                queryset=accounts,
                to_attr='coder_accounts',
            )) \
            .select_related('module') \
            .annotate(num_contests=SubquerySum('account__n_contests', filter=accounts_filter)) \
            .annotate(num_accounts=SubqueryCount('account', filter=accounts_filter)) \
            .filter(num_accounts__gt=0).order_by('-num_contests')

    return {
        'statistics': statistics,
        'writers': writers,
        'resources': resources,
        'profiles': profiles,
    }


@page_templates((
    ('profile_contests_paging.html', 'contest_page'),
    ('profile_writers_paging.html', 'writers_page'),
))
@context_pagination()
def profiles(request, query, template='profile_mixed.html'):
    data = _get_data_mixed_profile(request, query)
    context = get_profile_context(request, data['statistics'], data['writers'], data['resources'])
    context['profiles'] = data['profiles']
    context['query'] = query
    return template, context


def get_ratings_data(request, username=None, key=None, host=None, statistics=None, date_from=None, date_to=None,
                     with_global=False):
    if statistics is None:
        if username is not None:
            coder = get_object_or_404(Coder, username=username)
            statistics = Statistics.objects.filter(account__coders=coder)
            with_global = True
        else:
            resource = get_object_or_404(Resource, host=host)
            account = get_object_or_404(Account, key=key, resource=resource)
            statistics = Statistics.objects.filter(account=account)
        resource = request.GET.get('resource')
        if resource:
            statistics = statistics.filter(contest__resource__host=resource)

    resources = {r.pk: r for r in Resource.objects.filter(has_rating_history=True)}

    base_qs = (
        statistics
        .annotate(date=F('contest__end_time'))
        .annotate(name=F('contest__title'))
        .annotate(key=F('contest__key'))
        .annotate(kind=F('contest__kind'))
        .annotate(resource=F('contest__resource'))
        .annotate(score=F('solving'))
        .annotate(addition_solved=KeyTextTransform('solved', 'addition'))
        .annotate(solved=Cast(KeyTextTransform('solving', 'addition_solved'), IntegerField()))
        .annotate(problems=Cast(KeyTextTransform('problems', 'contest__info'), JSONField()))
        .annotate(division=KeyTextTransform('division', 'addition'))
        .annotate(cid=F('contest__pk'))
        .annotate(sid=F('pk'))
        .filter(contest__is_rated=True)
        .order_by('date')
    )

    qs = (
        base_qs
        .annotate(rating_change=Cast(KeyTextTransform('rating_change', 'addition'), IntegerField()))
        .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField()))
        .annotate(old_rating=Cast(KeyTextTransform('old_rating', 'addition'), IntegerField()))
        .annotate(is_unrated=Cast(KeyTextTransform('is_unrated', 'contest__info'), IntegerField()))
        .filter(Q(is_unrated__isnull=True) | Q(is_unrated=0))
        .filter(Q(new_rating__isnull=False) | Q(addition___rating_data__isnull=False))
    )

    qs_values = (
        'cid', 'sid', 'name', 'key', 'kind', 'date',
        'new_rating', 'old_rating', 'rating_change',
        'place', 'score', 'solved',
        'problems', 'division', 'addition___rating_data',
        'resource', 'addition',
    )

    qs = qs.values(*qs_values)

    ratings = {
        'status': 'ok',
        'data': {},
    }

    ratings['data']['resources'] = {}

    def dict_to_float_values(data):
        ret = {}
        for k, v in data.items():
            if k.startswith('_') or k in django_settings.ADDITION_HIDE_FIELDS_ or isinstance(v, (list, tuple)):
                continue
            if isinstance(v, dict):
                d = dict_to_float_values(v)
                for subk, subv in d.items():
                    ret[f'{k}__{subk}'] = subv
                continue
            if isinstance(v, str):
                v = asfloat(v)
            if v is None:
                continue
            ret[k] = v
        return ret

    qs = [stat for stat in qs if stat['resource'] in resources]
    n_resources = len({stat['resource'] for stat in qs})

    if with_global:
        global_qs = (
            base_qs
            .annotate(rating_change=F('global_rating_change'))
            .annotate(new_rating=F('new_global_rating'))
            .annotate(old_rating=Value(None, IntegerField(null=True)))
            .annotate(resource=Value(0, IntegerField()))
            .filter(new_rating__isnull=False)
        )
        qs.extend(global_qs.values(*qs_values))

    for stat in qs:
        if stat['addition___rating_data'] and n_resources > 1:
            continue

        addition = stat.pop('addition', {})
        addition['n_solved'] = stat['solved']
        addition['place'] = stat['place']
        addition['score'] = stat['score']
        stat['values'] = dict_to_float_values(addition)

        if stat['resource'] == 0:  # global rating
            resource = None
            default_info = dict(django_settings.CLIST_RESOURCE_DICT_)
            resource_key = default_info['host']
        else:
            resource = resources[stat['resource']]
            is_major_kind = resource.is_major_kind(stat['kind'])
            default_info = dict(resource.info.get('ratings', {}).get('chartjs', {}))
            default_info['pk'] = stat['resource']
            default_info['kind'] = None if is_major_kind else stat['kind']
            default_info['host'] = resource.host
            default_info['colors'] = resource.ratings
            default_info['icon'] = resource.icon
            resource_key = resource.host if is_major_kind else f'{resource.host} ({stat["kind"]})'
        default_info['fields'] = set()

        resource_info = ratings['data']['resources'].setdefault(resource_key, default_info)
        resource_info.setdefault('data', [])
        resource_info['fields'] |= set(stat['values'].keys())

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
            division = stat['division']
            problems = stat.pop('problems', {})
            if division and 'division' in problems:
                problems = problems['division'][division]
            if problems:
                stat['n_problems'] = len(problems)

            if stat['rating_change'] is not None and stat['old_rating'] is None:
                stat['old_rating'] = stat['new_rating'] - stat['rating_change']

            resource_info['data'].append(stat)

    qs = statistics.filter(contest__resource__has_rating_history=True,
                           contest__resource__info__ratings__external=True,
                           account__info___rating_data__isnull=False)
    resources_list = qs.distinct('contest__resource__host').values_list('contest__resource__pk', flat=True)
    for pk in resources_list:
        resource = resources[pk]
        default_info = dict(resource.info.get('ratings', {}).get('chartjs', {}))
        default_info['pk'] = pk
        default_info['host'] = resource.host
        default_info['colors'] = resource.ratings
        default_info['icon'] = resource.icon
        resource_info = ratings['data']['resources'].setdefault(resource.host, default_info)
        resource_info.setdefault('data', [])
        for stat in qs.filter(contest__resource__pk=pk).distinct('account__key'):
            data = resource.plugin.Statistic.get_rating_history(stat.account.info['_rating_data'],
                                                                stat,
                                                                resource,
                                                                date_from=date_from,
                                                                date_to=date_to)
            if data:
                resource_info['data'].extend(data)

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
        resource_info['fields'] = list(sorted(resource_info.get('fields', [])))

    ratings['data']['dates'] = list(sorted(set(dates)))
    return ratings


def ratings(request, username=None, key=None, host=None, query=None):
    if query:
        data = _get_data_mixed_profile(request, query)
        ratings_data = get_ratings_data(request=request, statistics=data['statistics'])
    else:
        ratings_data = get_ratings_data(
            request=request,
            username=username,
            key=key,
            host=host,
        )
    return JsonResponse(ratings_data)


@login_required
def settings(request, tab=None):
    coder = request.as_coder or request.user.coder
    notification_form = NotificationForm(coder)
    if request.method == 'POST':
        if request.POST.get('action', None) == 'notification':
            pk = request.POST.get('pk')
            instance = Notification.objects.get(pk=pk) if pk else None
            notification_form = NotificationForm(coder, request.POST, instance=instance)
            if notification_form.is_valid():
                notification = notification_form.save(commit=False)
                if pk:
                    notification.last_time = timezone.now()
                if notification.method == django_settings.NOTIFICATION_CONF.TELEGRAM and not coder.chat:
                    return HttpResponseRedirect(django_settings.HTTPS_HOST_ + reverse('telegram:me'))
                notification.coder = coder
                notification.save()
                request.logger.success(f'{"Updated" if pk else "Created"} notification')
                return HttpResponseRedirect(reverse('coder:settings', kwargs=dict(tab='notifications')))

    resources = coder.get_ordered_resources()
    coder.filter_set.filter(resources=[], contest__isnull=True, party__isnull=True).delete()

    if request.user.has_perm('my_oauth.view_disabled_services'):
        services = Service.objects
    else:
        services = Service.active_objects
    services = services.annotate(n_tokens=Count('token')).order_by('-n_tokens')

    selected_resource = request.GET.get('resource')
    selected_account = None
    if selected_resource:
        selected_resource = Resource.objects.filter(host=selected_resource).first()
        selected_account = request.GET.get('account')
        if selected_account:
            selected_account = Account.objects.filter(resource=selected_resource, key=selected_account).first()

    categories = coder.get_categories()
    custom_categories = {c.get_notification_method(): c.title for c in coder.chat_set.filter(is_group=True)}

    my_lists = coder.my_list_set.annotate(n_records=SubqueryCount('values'))

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
            "my_lists": my_lists,
            "categories": categories,
            "calendars": coder.calendar_set.order_by('-modified'),
            "subscriptions": coder.subscription_set.order_by('-modified'),
            "event_description": Calendar.EventDescription,
            "custom_categories": custom_categories,
            "coder_notifications": coder.notification_set.order_by('method'),
            "notifications": coder.get_notifications(),
            "notification_form": notification_form,
            "modules": Module.objects.select_related('resource').order_by('resource__id').all(),
            "ace_calendars": django_settings.ACE_CALENDARS_,
            "custom_countries": django_settings.CUSTOM_COUNTRIES_,
            "past_calendar_actions": django_settings.PAST_CALENDAR_ACTIONS_,
            "tab": tab,
        },
    )


@job
def call_command_parse_statistics(**kwargs):
    return call_command('parse_statistic', **kwargs)


@require_http_methods(['POST'])
def change(request):
    name = request.POST.get("name", None)
    value = request.POST.get("value", None)

    if value in ["true", "false"]:
        value = "1" if value == "true" else "0"

    user = request.user

    if not user.is_authenticated:
        referer_url = relative_url(request.META.get('HTTP_REFERER') or '/')
        auth_url = reverse('auth:login')
        url = f'{auth_url}?next={quote_url(referer_url)}'
        if request.is_ajax():
            return JsonResponse({'redirect': url, 'message': 'redirect'}, status=HttpResponseForbidden.status_code)
        return redirect(url)

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
        if value not in ["0", "1"]:
            return HttpResponseBadRequest("invalid check timezone value")
        coder.settings["check_timezone"] = int(value)
        coder.save()
    elif name == "show-tags":
        if value not in ["0", "1"]:
            return HttpResponseBadRequest("invalid show tags value")
        coder.settings["show_tags"] = int(value)
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
    elif name == "past-action-in-calendar":
        value = request.POST.get("value", None)
        if value not in django_settings.PAST_CALENDAR_ACTIONS_:
            return HttpResponseBadRequest("invalid past-action-in-calendar value")
        coder.settings["past_action_in_calendar"] = value
        coder.save()
    elif name == "event-limit-calendar":
        value = request.POST.get("value", None)
        if value not in ["true", "false"]:
            if not value.isdigit() or len(value) > 2 or int(value) < 1 or int(value) >= 20:
                return HttpResponseBadRequest("invalid event-limit-calendar value")
        coder.settings["event_limit_calendar"] = value
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
    elif name in ["hide-contest", "all-standings", "open-new-tab", "group-in-list", "calendar-filter-long",
                  "favorite-contests", "favorite-problems"]:
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

            field = "Start time"
            start_time_from = request.POST.get("value[start_time][from]", None)
            filter_.start_time_from = float(start_time_from) if start_time_from and start_time_from != "NaN" else None

            start_time_to = request.POST.get("value[start_time][to]", None)
            filter_.start_time_to = float(start_time_to) if start_time_to and start_time_to != "NaN" else None

            if filter_.start_time_from and filter_.start_time_to and filter_.start_time_from > filter_.start_time_to:
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
                raise Exception("invalid resources")

            field = "Host"
            host = request.POST.get("value[host]", None)
            filter_.host = host if host else None

            field = "Contest"
            contest_id = request.POST.get("value[contest]", None)
            if contest_id:
                filter_.contest = Contest.objects.get(pk=contest_id)
            else:
                filter_.contest = None

            field = "Party"
            party_id = request.POST.get("value[party]", None)
            if party_id:
                filter_.party = Party.objects.get(pk=party_id)
            else:
                filter_.party = None

            field = "Resources and contest and party"
            if not filter_.resources and not filter_.contest and not filter_.party:
                raise Exception("empty")

            categories = [c['id'] for c in coder.get_categories()]
            field = "Categories"
            filter_.categories = request.POST.getlist("value[categories][]", [])
            if not all([c in categories for c in filter_.categories]):
                raise Exception("invalid value(s)")
            if len(filter_.categories) == 0:
                raise Exception("empty")
            if filter_.categories != Filter.CATEGORIES:
                filter_.categories.sort()

            field = "Week days"
            filter_.week_days = [int(d) for d in request.POST.getlist("value[week_days][]", [])]
            if len(filter_.week_days) != len(set(filter_.week_days)):
                raise Exception("Duplicate week days")
            allow_days = set(range(1, 8))
            if any([d not in allow_days for d in filter_.week_days]):
                raise Exception(f"Week days should be in {allow_days}")
            filter_.week_days.sort()

            filter_.save()
        except Exception as e:
            return HttpResponseBadRequest("%s: %s" % (field, e))
    elif name == "add-filter":
        if coder.filter_set.filter(contest__isnull=True).count() >= 50:
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
    elif name in ("enable-filter", "disable-filter"):
        try:
            with transaction.atomic():
                enabled = name == "enable-filter"
                id_ = int(request.POST.get("id", -1))
                filter_ = Filter.objects.get(pk=id_, coder=coder, enabled=not enabled)
                filter_.enabled = enabled
                for category in filter_.categories:
                    Notification.objects.filter(coder=coder, method__endswith=category).update(last_time=None)
                filter_.save(update_fields=['enabled'])
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "add-list":
        if not value:
            return HttpResponseBadRequest("empty list name")
        if coder.my_list_set.count() >= 50:
            return HttpResponseBadRequest("reached the limit number of lists")
        if coder.my_list_set.filter(name=value):
            return HttpResponseBadRequest("duplicate list name")
        coder_list = CoderList.objects.create(owner=coder, name=value)
        return HttpResponse(json.dumps({'id': coder_list.pk, 'name': coder_list.name}), content_type="application/json")
    elif name == "edit-list":
        if not value:
            return HttpResponseBadRequest("empty list name")
        if coder.my_list_set.filter(name=value):
            return HttpResponseBadRequest("duplicate list name")
        try:
            pk = int(request.POST.get("id", -1))
            coder_list = CoderList.objects.get(pk=pk, owner=coder)
            coder_list.name = value
            coder_list.save()
        except Exception as e:
            return HttpResponseBadRequest(e)
        return HttpResponse(json.dumps({'id': coder_list.pk, 'name': coder_list.name}), content_type="application/json")
    elif name == "delete-list":
        try:
            pk = int(request.POST.get("id", -1))
            coder_list = CoderList.objects.get(pk=pk, owner=coder)
            coder_list.delete()
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name in ["add-calendar", "edit-calendar"]:
        try:
            pk = int(request.POST.get("id") or -1)

            if not value:
                return HttpResponseBadRequest("empty calendar name")
            if name == "add-calendar" and coder.calendar_set.count() >= 50:
                return HttpResponseBadRequest("reached the limit number of calendars")
            if coder.calendar_set.filter(name=value).exclude(pk=pk):
                return HttpResponseBadRequest("duplicate calendar name")

            category = request.POST.get("category") or None
            if category:
                categories = [c['id'] for c in coder.get_categories()]
                if category not in categories:
                    return HttpResponseBadRequest("not found calendar filter")

            resources = [int(x) for x in request.POST.getlist("resources[]", []) if x]
            if resources and Resource.objects.filter(pk__in=resources).count() != len(resources):
                return HttpResponseBadRequest("invalid resources")

            descriptions = [int(x) for x in request.POST.getlist("descriptions[]", []) if x]
            if len(set(descriptions)) != len(descriptions):
                return HttpResponseBadRequest("duplicate description elements")

            if name == "add-calendar":
                calendar = Calendar.objects.create(coder=coder, name=value, category=category, resources=resources,
                                                   descriptions=descriptions)
            elif name == "edit-calendar":
                calendar = Calendar.objects.get(pk=pk, coder=coder)
                calendar.name = value
                calendar.category = category
                calendar.resources = resources
                calendar.descriptions = descriptions
                calendar.save()
        except Exception as e:
            return HttpResponseBadRequest(e)
        return HttpResponse(json.dumps({'id': calendar.pk, 'name': calendar.name, 'filter': calendar.category}),
                            content_type="application/json")
    elif name == "delete-calendar":
        try:
            pk = int(request.POST.get("id", -1))
            calendar = Calendar.objects.get(pk=pk, coder=coder)
            calendar.delete()
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
    elif name == "add-subscription":
        if coder.subscription_set.count() >= 50:
            return HttpResponseBadRequest("reached the limit number of subscriptions")
        contest = get_object_or_404(Contest, pk=request.POST.get("contest"))
        account = get_object_or_404(Account, pk=request.POST.get("account"))
        method = request.POST.get("method")
        categories = [k for k, v in coder.get_notifications()]
        if method not in categories:
            return HttpResponseBadRequest("invalid method value")
        sub, created = Subscription.objects.get_or_create(
            coder=coder,
            method=method,
            contest=contest,
            account=account,
        )
        return HttpResponse("created" if created else "ok")
    elif name == "delete-subscription":
        pk = int(request.POST.get("id", -1))
        sub = Subscription.objects.get(pk=pk, coder=coder)
        sub.delete()
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
        try:
            if "resource" in request.POST:
                resource_id = int(request.POST.get("resource"))
                resource = Resource.objects.get(pk=resource_id)
                account = Account.objects.get(resource=resource, key=value)
            else:
                account = Account.objects.get(pk=request.POST.get("id"))
                resource = account.resource

            if account.coders.filter(pk=coder.id).first():
                raise Exception('Account is already connect to you')

            if resource.with_single_account():
                if coder.account_set.filter(resource=resource).exists():
                    raise Exception('Allow only one account for resource')
                if account.coders.filter(is_virtual=False).exists():
                    raise Exception('Account is already connect')

            need_verification = account.need_verification
            if not need_verification and resource.has_account_verification:
                need_verification = account.coders.exists()
            if need_verification:
                need_verification = not VerifiedAccount.objects.filter(coder=coder, account=account).exists()
            if need_verification:
                url = reverse('coder:account_verification', kwargs=dict(key=account.key, host=resource.host))
                return JsonResponse({'url': url, 'message': 'redirect'}, status=HttpResponseRedirect.status_code)

            coder.add_account(account)
            return HttpResponse(json.dumps(account.dict()), content_type="application/json")
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "delete-account":
        try:
            pk = request.POST.get("id")
            if pk:
                account = Account.objects.get(pk=int(pk))
            else:
                if not value:
                    return HttpResponseBadRequest("empty account value")
                host = request.POST.get("resource")
                resource = Resource.objects.get(host=host)
                account = Account.objects.get(resource=resource, key=value)
            account.coders.remove(coder)
            account.updated = timezone.now()
            account.save()
        except Exception as e:
            return HttpResponseBadRequest(e)
    elif name == "update-account":
        try:
            pk = request.POST.get('id')
            if request.user.has_perm('ranking.update_account'):
                account = Account.objects.get(pk=int(pk))
            else:
                account = Account.objects.get(pk=int(pk), coders=coder)
        except Exception as e:
            return HttpResponseBadRequest(e)

        if not account.resource.has_accounts_infos_update:
            return HttpResponseBadRequest(f'Update not supported for {account.resource.host} resource')
        now = timezone.now()
        if account.updated and account.updated <= now:
            return HttpResponseBadRequest('Update in progress')

        usage = get_usage(request, group='update-account', key='user', rate='10/h', increment=True)
        if usage['should_limit']:
            delta = timedelta(seconds=usage['time_left'])
            return HttpResponseBadRequest(f'Try again in {humanize.naturaldelta(delta)}', status=429)
        account.updated = now
        account.save()
    elif name == "update-statistics":
        usage = get_usage(request, group='update-statistics', key='user', rate='20/h', increment=True)
        if usage['should_limit']:
            delta = timedelta(seconds=usage['time_left'])
            return HttpResponseBadRequest(f'Try again in {humanize.naturaldelta(delta)}', status=429)

        pk = request.POST.get('id')
        contest = get_object_or_404(Contest, pk=pk)
        if not has_update_statistics_permission(user, contest):
            return HttpResponseBadRequest('You have no permission to update statistics for this contest')

        call_command_parse_statistics.delay(contest_id=pk)
    elif name == "pre-delete-user":
        class RollbackException(Exception):
            pass
        try:
            with transaction.atomic():
                n_accounts = user.coder.account_set.count()
                user.coder.account_set.clear()
                _, delete_info = user.delete()
                if n_accounts:
                    delete_info.setdefault('ranking.Account_coders', n_accounts)
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
        with transaction.atomic():
            user.delete()
    elif name == "activity":
        if value not in ['1', '0']:
            return HttpResponseBadRequest('invalid value')
        value = int(value)
        content_type = request.POST.get('content_type')
        object_id = request.POST.get('object_id')
        activity_type = request.POST.get('activity_type')
        if content_type == 'problem':
            content_type = ContentType.objects.get(app_label='clist', model='problem')
        elif activity_type in [Activity.Type.TODO, Activity.Type.SOLVED, Activity.Type.REJECT]:
            return HttpResponseBadRequest('invalid activity type')
        elif content_type == 'contest':
            content_type = ContentType.objects.get(app_label='clist', model='contest')
        else:
            return HttpResponseBadRequest('invalid content type')

        kwargs = dict(
            coder=coder,
            content_type=content_type,
            object_id=object_id,
            activity_type=activity_type,
        )
        if value:
            Activity.objects.get_or_create(**kwargs)

            excluding_content_types_groups = [
                {Activity.Type.SOLVED, Activity.Type.REJECT, Activity.Type.TODO},
            ]
            for group in excluding_content_types_groups:
                if activity_type in group:
                    for other_activity_type in group:
                        if activity_type == other_activity_type:
                            continue
                        kwargs['activity_type'] = other_activity_type
                        Activity.objects.filter(**kwargs).delete()
        else:
            Activity.objects.filter(**kwargs).delete()

        return JsonResponse({'status': 'ok', 'state': value})
    elif name == "note":
        content_type = request.POST.get('content_type')
        object_id = request.POST.get('object_id')
        if content_type == 'problem':
            content_type = ContentType.objects.get(app_label='clist', model='problem')

        kwargs = dict(
            coder=coder,
            content_type=content_type,
            object_id=object_id,
        )

        action = request.POST.get('action')

        if action == 'change':
            if not value:
                return HttpResponseBadRequest('empty value')
            if len(value) > 1000:
                return HttpResponseBadRequest('too long value')
            note, created = Note.objects.get_or_create(**kwargs)
            note.text = value
            note.save(update_fields=['text'])
        elif action == 'delete':
            Note.objects.filter(**kwargs).delete()
            value = ''
        else:
            return HttpResponseBadRequest(f'unknown action = {action}')

        return JsonResponse({'status': 'ok', 'state': value})
    else:
        return HttpResponseBadRequest(f'unknown query = {name}')

    return HttpResponse('accepted')


def search(request, **kwargs):
    query = request.GET.get('query', None)
    if not query or not isinstance(query, str):
        return HttpResponseBadRequest('invalid query')

    count = int(request.GET.get('count', django_settings.DEFAULT_COUNT_QUERY_))
    count = min(count, django_settings.DEFAULT_COUNT_LIMIT_)
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
        qs = qs.order_by('-n_accounts', 'pk')

        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.host, 'icon': r.icon} for r in qs]
    elif query == 'contests':
        qs = Contest.objects.select_related('resource')
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'title'))
        if request.GET.get('has_problems') in django_settings.YES_:
            qs = qs.filter(info__problems__isnull=False, stage__isnull=True).exclude(info__problems__exact=[])
        if request.GET.get('has_statistics') in django_settings.YES_:
            qs = qs.filter(n_statistics__gt=0)
        resources = [r for r in request.GET.getlist('resources[]') if r]
        if resources:
            qs = qs.filter(resource__pk__in=resources)
        qs = qs.order_by('-end_time', 'pk')
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.title, 'icon': r.resource.icon} for r in qs]
    elif query == 'show-filter':
        coder = request.user.coder
        filter_ = Filter.objects.get(pk=request.GET.get('id'), coder=coder)
        contest_filter = coder.get_contest_filter(filters=[filter_])
        if not filter_.to_show:
            contest_filter = ~contest_filter
        qs = Contest.visible.select_related('resource').filter(contest_filter)
        qs = qs.order_by('-end_time', 'pk')
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.title, 'icon': r.resource.icon, 'url': r.actual_url} for r in qs]
    elif query == 'series':
        qs = ContestSeries.objects.all()
        qs = qs.annotate(n_contests=SubqueryCount('contest'))
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'name', 'short'))
        qs = qs.order_by('-n_contests', '-pk')
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'slug': r.slug, 'text': r.text, 'short': r.short, 'name': r.name} for r in qs]
    elif query == 'tags':
        qs = ProblemTag.objects.all()
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'name'))
        qs = qs.order_by('name')

        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.name} for r in qs]
    elif query == 'resources-for-add-account' and request.user.is_authenticated:
        coder = request.user.coder
        coder_accounts = coder.account_set.filter(resource=OuterRef('pk'))

        qs = Resource.objects \
            .annotate(has_coder_account=Exists(coder_accounts)) \
            .annotate(has_multi=F('has_multi_account')) \
            .annotate(disabled=Case(
                When(module__isnull=True, then=Value(True)),
                When(has_coder_account=True, has_multi=False, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ))
        if 'regex' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET['regex'], 'host'))
        qs = qs.order_by('disabled', 'pk')

        qs = qs[(page - 1) * count:page * count]
        ret = [
            {
                'id': r.id,
                'text': r.host,
                'disabled': r.disabled,
            }
            for r in qs
        ]
    elif query == 'organization':
        qs = Organization.objects.all()

        name = request.GET.get('name')
        if name:
            qs = qs.filter(Q(name__icontains=name) | Q(name_ru__icontains=name) | Q(abbreviation__icontains=name))

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
        ).order_by('disabled', '-modified', 'pk')

        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.name, 'disabled': r.disabled} for r in qs]
    elif query == 'country':
        qs = list(countries)
        name = request.GET.get('name')
        if name:
            name = name.lower()
            qs = [(c, n) for c, n in countries if name in n.lower()]
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c, 'text': n} for c, n in qs]
    elif query == 'account-for-add-subscription':
        contest = get_object_or_404(Contest, pk=request.GET.get('contest'))
        qs = contest.statistics_set.select_related('account')
        search = request.GET.get('search')
        if search:
            qs = qs.filter(Q(account__key__icontains=search) | Q(account__name__icontains=search))
        qs = qs.order_by('place', '-solving')
        qs = qs[(page - 1) * count:page * count]
        ret = [
            {
                'id': s.account.id,
                'text': f'{s.account.key}, {s.account.name}' if s.account.name else s.account.key,
            }
            for s in qs
        ]
    elif query == 'contest-for-add-subscription':
        qs = Contest.objects.filter(n_statistics__gt=0, end_time__gte=timezone.now())
        regex = request.GET.get('regex')
        if regex:
            qs = qs.filter(title__iregex=verify_regex(regex))
        qs = qs.order_by('-end_time', 'pk')
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c.id, 'text': c.title} for c in qs]
    elif query == 'notpast':
        qs = Contest.objects.filter(end_time__gte=timezone.now())
        regex = request.GET.get('regex')
        if regex:
            qs = qs.filter(title__iregex=verify_regex(regex))
        qs = qs.order_by('-end_time', 'pk')
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c.id, 'text': c.title} for c in qs]
    elif query == 'party':
        name = request.GET.get('name')
        qs = Party.objects.filter(name__iregex=verify_regex(name))
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': c.id, 'text': c.name} for c in qs]
    elif query == 'field-to-select':
        contest = get_object_or_404(Contest, pk=request.GET.get('cid'))
        text = request.GET.get('text')
        field = request.GET.get('field')
        assert '__' not in field

        view_private_fields = request.user.has_perm('view_private_fields', contest.resource)
        if field.startswith('_') and not view_private_fields:
            return HttpResponseBadRequest('You have no permission to view this field')

        if field == 'languages':
            qs = contest.info.get('languages', [])
            qs = ['any'] + [q for q in qs if not text or text.lower() in q.lower()]
        elif field == 'verdicts':
            qs = contest.info.get('verdicts', [])
            qs = [q for q in qs if not text or text.lower() in q.lower()]
        elif field == 'rating':
            qs = ['rated', 'unrated']
        elif f'_{field}' in contest.info:
            if not view_private_fields:
                return HttpResponseBadRequest('You have no permission to view this field')
            qs = ['any'] + contest.info.get(f'_{field}')
            qs = [v for v in qs if not text or text.lower() in str(v).lower()]
        elif field in contest.info.get('fields', []):
            field = f'addition__{field}'
            qs = contest.statistics_set
            if text:
                qs = qs.filter(**{f'{field}__icontains': text})
            qs = qs.distinct(field).values_list(field, flat=True)
        else:
            return HttpResponseBadRequest('Invalid field')

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
        qs = qs.order_by(*order, 'pk')

        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': r.id, 'text': r.username} for r in qs]
    elif query == 'accounts':
        qs = Account.objects.all()
        if request.GET.get('resource'):
            qs = qs.filter(resource_id=int(request.GET.get('resource')))

        order = ['-n_contests', 'pk']
        if 'regex' in request.GET:
            re_search = request.GET['regex']

            exact_qs = qs.filter(key__iexact=re_search)
            if exact_qs.exists():
                qs = exact_qs
            else:
                qs = qs.filter(get_iregex_filter(re_search, 'key', 'name'))
                search_striped = re_search.rstrip('$').lstrip('^')
                qs = qs.annotate(match=Case(
                    When(Q(key__iexact=search_striped) | Q(name__iexact=search_striped), then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField(),
                ))
                order.insert(0, '-match')
        qs = qs.select_related('resource')
        qs = qs.order_by(*order, 'pk')

        qs = qs[(page - 1) * count:page * count]
        ret = [
            {
                'id': r.id,
                'text': f'{r.key}, {r.name}, {r.resource.host}' if r.name else f'{r.key}, {r.resource.host}'
            } for r in qs
        ]
    else:
        return HttpResponseBadRequest(f'invalid query = {query}')

    result = {
        'items': ret,
        'more': len(ret) and len(ret) == count,
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

    contests = Contest.objects.filter(rating__party=party).select_related('resource')
    future = contests.filter(end_time__gt=timezone.now()).order_by('start_time')

    statistics = Statistics.objects.filter(
        account__coders__in=party.coders.all(),
        contest__in=party_contests.filter(start_time__lt=timezone.now()),
        contest__end_time__lt=timezone.now(),
    ) \
        .order_by('-contest__end_time') \
        .select_related('contest', 'account', 'contest__resource') \
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


def view_list(request, uuid):
    qs = CoderList.objects
    qs = qs.prefetch_related('values__account__resource')
    qs = qs.prefetch_related('values__coder')
    coder_list = get_object_or_404(qs, uuid=uuid)
    coder = request.user.coder if request.user.is_authenticated else None

    is_owner = coder_list.owner == coder
    can_modify = is_owner

    request_post = request.session.pop('view_list_request_post', None) or request.POST
    if request_post:
        if not can_modify:
            return HttpResponseBadRequest('Only the owner can change the list')
        if 'uuid' in request_post and request_post['uuid'] != uuid:
            return HttpResponseBadRequest('Wrong uuid value')
        group_id = toint(request_post.get('gid'))
        if not group_id:
            group_id = (coder_list.values.aggregate(val=Max('group_id')).get('val') or 0) + 1

        def add_coder(c):
            if ListValue.objects.filter(coder_list=coder_list).count() >= django_settings.CODER_LIST_N_VALUES_LIMIT_:
                request.logger.warning(f'Limit reached. Coder {c.username} not added')
                return
            try:
                ListValue.objects.create(coder_list=coder_list, coder=c, group_id=group_id)
                request.logger.success(f'Added {c.username} coder to list')
            except IntegrityError:
                request.logger.warning(f'Coder {c.username} has already been added')

        def add_account(a):
            if ListValue.objects.filter(coder_list=coder_list).count() >= django_settings.CODER_LIST_N_VALUES_LIMIT_:
                request.logger.warning(f'Limit reached. Account {a.key} not added')
                return
            try:
                ListValue.objects.create(coder_list=coder_list, account=a, group_id=group_id)
                request.logger.success(f'Added {a.key} account to list')
            except IntegrityError:
                request.logger.warning(f'Account {a.key} has already been added')

        if request_post.get('coder'):
            c = get_object_or_404(Coder, pk=request_post.get('coder'))
            add_coder(c)
        elif request_post.get('account'):
            a = get_object_or_404(Account, pk=request_post.get('account'))
            add_account(a)
        elif request_post.get('delete_gid'):
            group_id = request_post.get('delete_gid')
            deleted, *_ = coder_list.values.filter(group_id=group_id).delete()
            if deleted:
                request.logger.success('Deleted from list')
            else:
                request.logger.warning('Nothing has been deleted')
        elif request_post.get('raw'):
            raw = request_post.get('raw')
            lines = raw.strip().split()

            if request_post.get('gid'):
                if len(lines) > 1:
                    request.logger.warning(f'Ignore {len(lines) - 1} line(s)')
                lines = lines[:1]

            for line in lines:
                values = line.strip().split(',')
                n_coders = 0
                n_accounts = 0
                for value in values:
                    try:
                        if ':' not in value:
                            if n_coders:
                                request.logger.warning(f'Coder must be one, value = "{value}"')
                                continue
                            coders = list(Coder.objects.filter(username=value))
                            if not coders:
                                request.logger.warning(f'Not found coder, value = "{value}"')
                                continue
                            if len(coders) > 1:
                                request.logger.warning(f'Too many coders found = "{coders}", value = "{value}"')
                                continue
                            add_coder(coders[0])
                            n_coders += 1
                        else:
                            host, account = value.split(':', 1)
                            resources = list(Resource.objects.filter(Q(host=host) | Q(short_host=host)))
                            if not resources:
                                request.logger.warning(f'Not found host = "{host}", value = "{value}"')
                                continue
                            if len(resources) > 1:
                                request.logger.warning(f'Too many resources found = "{resources}", value = "{value}"')
                                continue
                            resource = resources[0]
                            accounts = list(Account.objects.filter(resource=resource, key=account))
                            if not accounts:
                                request.logger.warning(f'Not found account = "{account}", value = "{value}"')
                                continue
                            if len(accounts) > 1:
                                request.logger.warning(f'Too many accounts found = "{accounts}", value = "{value}"')
                                continue
                            add_account(accounts[0])
                            n_accounts += 1
                    except Exception:
                        request.logger.error(f'Some problem with value = "{value}"')
                group_id += 1
        return HttpResponseRedirect(request.path)

    coder_values = {}
    for v in coder_list.values.all():
        data = coder_values.setdefault(v.group_id, {})
        data.setdefault('list_values', []).append(v)

    for data in coder_values.values():
        vs = []
        for v in data['list_values']:
            if v.coder:
                vs.append(v.coder.username)
            elif v.account:
                prefix = v.account.resource.short_host or v.account.resource.host
                vs.append(f'{prefix}:{v.account.key}')
        data['versus'] = ','.join(vs)

    context = {
        'coder_list': coder_list,
        'coder_values': coder_values,
        'is_owner': is_owner,
        'can_modify': can_modify,
        'coder': coder,
    }

    if len(coder_values) > 1:
        context['versus'] = '/vs/'.join([d['versus'] for d in coder_values.values()])

    return render(request, 'coder_list.html', context)


@page_template('accounts_paging.html')
@context_pagination()
def accounts(request, template='accounts.html'):
    accounts = Account.objects.select_related('resource')
    accounts = accounts.annotate(has_coders=Exists('coders'))
    if request.user.is_authenticated:
        coder = request.user.coder
        accounts = accounts.annotate(my_account=Exists('coders', filter=Q(coder=coder)))
    params = {}

    action = request.GET.get('action')
    if request.user.has_perm('ranking.link_account'):
        link_coder = request.GET.get('coder')
        if link_coder:
            link_coder = Coder.objects.get(pk=link_coder)
            params['link_coders'] = [link_coder]
        link_accounts = request.GET.getlist('accounts')
        if link_accounts:
            params['link_accounts'] = set(link_accounts)
        if action == 'link':
            if link_accounts and link_coder:
                link_accounts = Account.objects.filter(pk__in=link_accounts)
                coder_url = reverse('coder:profile', args=[coder.username])
                message = f'Added by <a href="{coder_url}">{coder.display_name}</a>.'
                linked_accounts = []
                for a in link_accounts:
                    if a.coders.filter(pk=link_coder.pk).exists():
                        continue
                    a.coders.add(link_coder)
                    linked_accounts.append(a)
                if linked_accounts and not link_coder.is_virtual:
                    NotificationMessage.link_accounts(link_coder, linked_accounts, message=message, sender=coder)
                    request.logger.success(f'Linked {len(linked_accounts)} account(s) to {link_coder.username}')
            query = query_transform(request, with_remove=True, accounts=None, action=None)
            return HttpResponseRedirect(f'{request.path}?{query}')

    search = request.GET.get('search')
    if search:
        filt = get_iregex_filter(search, 'name', 'key', logger=request.logger)
        accounts = accounts.filter(filt)
        if request.user.has_perm('ranking.link_account'):
            coders_counter = Counter(accounts.filter(has_coders=True).values_list('coders__pk', flat=True))
            most_coder = coders_counter.most_common()
            if most_coder:
                link_coder, _ = most_coder[0]
                link_coder = Coder.objects.get(pk=link_coder)
                params['link_coders'] = [link_coder]

    countries = request.GET.getlist('country')
    countries = set([c for c in countries if c])
    if countries:
        accounts = accounts.filter(country__in=countries)
        params['countries'] = countries

    resources = request.GET.getlist('resource')
    resources = [r for r in resources if r]
    if resources:
        resources = Resource.objects.filter(pk__in=resources)
        accounts = accounts.filter(resource__in=resources)
        params['resources'] = resources

    # qualifiers
    contests_ids = request.GET.getlist('contest')
    contests_ids = [r for r in contests_ids if r]
    if contests_ids:
        contests = Contest.objects.filter(pk__in=contests_ids)
        params['contests'] = contests

        contest_filter = Q(contest__in=contests_ids)
        stats = Statistics.objects.filter(contest_filter)

        adv_options = stats.distinct('addition___advance__next').values_list('addition___advance__next', flat=True)
        advanced = request.GET.getlist('advanced')
        params['advanced_filter'] = {
            'values': advanced,
            'options': ['true', 'false'] + [a for a in adv_options if a],
            'noajax': True,
            'nomultiply': True,
            'nogroupby': True,
        }

        adv_filter = Q()
        for adv in advanced:
            if adv not in params['advanced_filter']['options']:
                continue
            if adv in ['true', 'false']:
                adv_filter |= Q(advanced=adv == 'true')
            else:
                adv_filter |= Q(addition___advance__next=adv, advanced=True)
            params['advanced_filter']['value'] = bool(advanced)
        stats = stats.filter(adv_filter)

        prefetch_stats = stats.select_related('contest').order_by('contest_id')

        accounts = (
            accounts
            .prefetch_related(Prefetch('statistics_set', prefetch_stats, to_attr='selected_stats'))
            .annotate(has_contests=Exists('statistics', filter=contest_filter & adv_filter))
            .filter(has_contests=True)
        )

        subquery = stats.filter(account=OuterRef('pk')).order_by('contest__start_time', 'contest_id', 'place_as_int')
        subquery = subquery[:1]
        accounts = accounts.annotate(selected_time=Subquery(subquery.values('contest__start_time')))
        accounts = accounts.annotate(selected_contest=Subquery(subquery.values('contest_id')))
        accounts = accounts.annotate(selected_place=Subquery(subquery.values('place_as_int')))

    context = {'params': params}
    addition_table_fields = ('modified', 'updated', 'created')
    table_fields = ('rating', 'n_contests', 'n_writers', 'last_activity') + addition_table_fields

    chart_field = request.GET.get('chart_column')
    groupby = request.GET.get('groupby')
    fields = request.GET.getlist('field')
    orderby = request.GET.get('sort_column')
    order = request.GET.get('sort_order') if orderby else None

    # custom fields
    custom_fields = set()
    fields_types = {}
    for resource in resources:
        for k, v in resource.accounts_fields.get('types', {}).items():
            if v == ['int'] or v == ['float'] and k not in table_fields:
                fields_types[k] = v
                custom_fields.add(k)
    custom_fields = list(sorted(custom_fields))
    if chart_field and chart_field not in table_fields:
        if chart_field not in custom_fields:
            chart_field = None
        elif chart_field not in fields:
            fields.append(chart_field)

    # chart
    if chart_field:
        if chart_field in table_fields:
            field = chart_field
            cast = None
        else:
            field = f'info__{chart_field}'
            cast = fields_types[chart_field][0]
        context['chart'] = make_chart(accounts, field=field, groupby=groupby, cast=cast, logger=request.logger)
        context['groupby'] = groupby
    else:
        context['chart'] = False

    # custom fields
    options = custom_fields + list(addition_table_fields)
    context['custom_fields'] = {
        'values': [v for v in fields if v and v in options],
        'options': options,
        'noajax': True,
        'nogroupby': True,
        'nourl': True,
    }
    for field in context['custom_fields']['values']:
        if field not in custom_fields:
            continue
        k = f'info__{field}'
        if field == orderby or field == chart_field:
            types = fields_types[field]
            if types == ['int']:
                accounts = accounts.annotate(**{k: Cast(JSONF(k), BigIntegerField())})
            elif types == ['float']:
                accounts = accounts.annotate(**{k: Cast(JSONF(k), FloatField())})
        else:
            accounts = accounts.annotate(**{k: JSONF(k)})

    # ordering
    if orderby == 'account':
        orderby = 'key'
    elif orderby in table_fields:
        pass
    elif orderby in custom_fields:
        orderby = f'info__{orderby}'
    elif params.get('advanced_filter'):
        orderby = ['selected_time', 'selected_contest', 'selected_place']
    elif orderby:
        request.logger.error(f'Not found `{orderby}` column for sorting')
        orderby = []
    orderby = orderby if not orderby or isinstance(orderby, list) else [orderby]
    if order in ['asc', 'desc']:
        orderby = [getattr(F(o), order)(nulls_last=True) for o in orderby]
    elif order:
        request.logger.warning(f'Not found `{order}` order for sorting')
    orderby = orderby or ['-created']
    accounts = accounts.order_by(*orderby)

    context['accounts'] = accounts
    context['resources_custom_fields'] = custom_fields

    return template, context
