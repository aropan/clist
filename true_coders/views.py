import collections
import re
import json
import logging


import pytz
from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.urls import reverse
from django.db.models import Count, F, Q, Exists, Case, When, Value, OuterRef, BooleanField, IntegerField, Prefetch
from django.db.models.functions import Cast
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from tastypie.models import ApiKey
from django_countries import countries
from el_pagination.decorators import page_template

from clist.models import Resource, Contest
from clist.templatetags.extras import get_timezones, format_time, slug as slugify
from clist.views import get_timezone, main
from ranking.models import Rating
from my_oauth.models import Service
from notification.forms import Notification, NotificationForm
from ranking.models import Statistics, Module, Account
from true_coders.models import Filter, Party, Coder, Organization
from events.models import Team, TeamStatus
from utils.regex import verify_regex, get_iregex_filter


logger = logging.getLogger(__name__)


@page_template('profile_contests_paging.html')
def profile(request, username, template='profile.html', extra_context=None):
    coder = get_object_or_404(Coder, user__username=username)
    statistics = Statistics.objects \
        .filter(account__coders=coder) \
        .select_related('contest', 'contest__resource', 'account') \
        .order_by('-contest__end_time')

    search = request.GET.get('search')
    if search:
        for search in search.split(' && '):
            if search.startswith('problem:'):
                _, search = search.split(':', 1)
                search_re = verify_regex(search)
                statistics = statistics.filter(addition__problems__iregex=f'"[^"]*{search_re}[^"]*"')
            elif search.startswith('contest:'):
                _, search = search.split(':', 1)
                statistics = statistics.filter(contest__id=search)
            elif search.startswith('account:'):
                _, search = search.split(':', 1)
                statistics = statistics.filter(account__key=search)
            elif search.startswith('resource:'):
                _, search = search.split(':', 1)
                statistics = statistics.filter(contest__resource__host=search)
            else:
                search_re = verify_regex(search)
                query = Q(contest__resource__host__iregex=search_re) | Q(contest__title__iregex=search_re)
                statistics = statistics.filter(query)

    history_resources = Statistics.objects \
        .filter(account__coders=coder) \
        .filter(contest__resource__has_rating_history=True) \
        .filter(contest__stage__isnull=True) \
        .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
        .filter(new_rating__isnull=False) \
        .annotate(host=F('contest__resource__host')) \
        .values('host') \
        .annotate(num_contests=Count('contest')) \
        .order_by('-num_contests')

    resources = Resource.objects \
        .prefetch_related(Prefetch(
            'account_set',
            queryset=Account.objects
            .filter(coders=coder)
            .annotate(num_stats=Count('statistics'))
            .order_by('-num_stats'),
            to_attr='coder_accounts',
        )) \
        .annotate(num_contests=Count(
            'contest',
            filter=Q(contest__in=Statistics.objects.filter(account__coders=coder).values('contest'))
        )) \
        .filter(num_contests__gt=0).order_by('-num_contests')

    context = {
        'coder': coder,
        'resources': resources,
        'statistics': statistics,
        'history_resources': history_resources,
    }

    if extra_context is not None:
        context.update(extra_context)
    return render(request, template, context)


def ratings(request, username):
    coder = get_object_or_404(Coder, user__username=username)
    qs = Statistics.objects \
        .annotate(date=F('contest__end_time')) \
        .annotate(name=F('contest__title')) \
        .annotate(host=F('contest__resource__host')) \
        .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
        .annotate(old_rating=Cast(KeyTextTransform('old_rating', 'addition'), IntegerField())) \
        .annotate(score=F('solving')) \
        .annotate(addition_solved=KeyTextTransform('solved', 'addition')) \
        .annotate(solved=Cast(KeyTextTransform('solving', 'addition_solved'), IntegerField())) \
        .annotate(problems=KeyTextTransform('problems', 'contest__info')) \
        .annotate(division=KeyTextTransform('division', 'addition')) \
        .annotate(cid=F('contest__pk')) \
        .annotate(ratings=F('contest__resource__ratings')) \
        .annotate(is_unrated=Cast(KeyTextTransform('is_unrated', 'contest__info'), IntegerField())) \
        .filter(Q(is_unrated__isnull=True) | Q(is_unrated=0)) \
        .filter(new_rating__isnull=False) \
        .filter(account__coders=coder) \
        .filter(contest__resource__has_rating_history=True) \
        .filter(contest__stage__isnull=True) \
        .order_by('date') \
        .values(
            'cid',
            'name',
            'host',
            'date',
            'new_rating',
            'old_rating',
            'place',
            'score',
            'ratings',
            'solved',
            'problems',
            'division',
        )

    ratings = {
        'status': 'ok',
        'data': {},
    }

    dates = list(sorted(set(r['date'] for r in qs)))
    ratings['data']['dates'] = dates
    ratings['data']['resources'] = {}

    for r in qs:
        colors = r.pop('ratings')

        division = r.pop('division')
        problems = json.loads(r.pop('problems') or '{}')
        if division and 'division' in problems:
            problems = problems['division'][division]
        r['n_problems'] = len(problems)

        date = r['date']
        if request.user.is_authenticated and request.user.coder:
            date = timezone.localtime(date, pytz.timezone(request.user.coder.timezone))
        r['when'] = date.strftime('%b %-d, %Y')
        resource = ratings['data']['resources'].setdefault(r['host'], {})
        resource['colors'] = colors
        if r['new_rating'] > resource.get('highest', {}).get('value', 0):
            resource['highest'] = {
                'value': r['new_rating'],
                'timestamp': int(date.timestamp()),
            }
        r['slug'] = slugify(r['name'])
        resource.setdefault('data', [])
        if resource['data'] and r['old_rating']:
            last = resource['data'][-1]
            if last['new_rating'] != r['old_rating']:
                logger.warning(f"coder = {coder}: prev = {last}, curr = {r}")
        resource['data'].append(r)

    return JsonResponse(ratings)


@login_required
def settings(request):
    coder = request.user.coder
    notification_form = NotificationForm(coder)
    if request.method == 'POST':
        if request.POST.get('action', None) == 'notification':
            notification_form = NotificationForm(coder, request.POST)
            if notification_form.is_valid():
                notification = notification_form.save(commit=False)
                if notification.method == Notification.TELEGRAM and not coder.chat:
                    return HttpResponseRedirect(django_settings.HTTPS_HOST_ + reverse('telegram:me'))
                notification.coder = coder
                notification.save()
                return HttpResponseRedirect(reverse('coder:settings') + '#notifications-tab')

    if request.GET.get('as_coder') and request.user.has_perm('as_coder'):
        coder = Coder.objects.get(user__username=request.GET['as_coder'])

    resources = Resource.objects.all()
    coder.filter_set.filter(resources=[], contest__isnull=True).delete()

    return render(
        request,
        "settings.html",
        {
            "resources": resources,
            "coder": coder,
            "services": Service.objects.all(),
            "categories": coder.get_categories(),
            "notification_form": notification_form,
            "modules": Module.objects.order_by('resource__id').all(),
        },
    )


@login_required
def change(request):
    name = request.POST.get("name", None)
    value = request.POST.get("value", None)

    if value in ["true", "false"]:
        value = "1" if value == "true" else "0"

    user = request.user
    coder = user.coder

    if coder.id != int(request.POST.get("pk", -1)):
        return HttpResponseBadRequest("invalid pk")
    if name == "timezone":
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
        if value not in [
            'enable',
            'disable',
            'apple',
            'google',
            'office365',
            'outlook',
            'outlookcom',
            'yahoo',
        ]:
            return HttpResponseBadRequest("invalid addtocalendar value")
        coder.settings["add_to_calendar"] = value
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

            categories = coder.get_categories()
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
    else:
        return HttpResponseBadRequest("unknown query")

    return HttpResponse("accepted")


@login_required
def search(request, **kwargs):
    query = request.GET.get('query', None)
    if not query or not isinstance(query, str):
        return HttpResponseBadRequest('invalid query')

    count = int(request.GET.get('count', 10))
    page = int(request.GET.get('page', 1))
    if query == 'resources-for-add-account':
        accounts = Account.objects.filter(resource=OuterRef('pk'))
        coder = request.user.coder
        coder_accounts = coder.account_set.filter(resource=OuterRef('pk'))

        qs = Resource.objects \
            .annotate(has_account=Exists(accounts)) \
            .annotate(has_coder_account=Exists(coder_accounts)) \
            .annotate(has_multi=F('module__multi_account_allowed')) \
            .annotate(disabled=Case(
                When(has_account=False, then=Value(True)),
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
    elif query == 'accounts-for-add-account':
        coder = request.user.coder

        qs = Account.objects.all()
        resource = request.GET.get('resource')
        if resource:
            qs = qs.filter(resource__id=int(resource))
        else:
            qs = qs.select_related('resource')
        if 'user' in request.GET:
            qs = qs.filter(get_iregex_filter(request.GET.get('user'), 'key', 'name'))

        qs = qs.annotate(has_multi=F('resource__module__multi_account_allowed')) \

        qs = qs.annotate(disabled=Case(
            When(coders=coder, then=Value(True)),
            When(coders__isnull=False, has_multi=False, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ))

        qs = qs.order_by('disabled')

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
        text = request.GET.get('text')
        field = request.GET.get('field')
        assert '__' not in field
        field = f'addition__{field}'
        contest = get_object_or_404(Contest, pk=request.GET.get('cid'))
        qs = contest.statistics_set.filter(**{f'{field}__icontains': text}).distinct(field).values_list(field)

        total = qs.count()
        qs = qs[(page - 1) * count:page * count]
        ret = [{'id': f[0], 'text': f[0]} for f in qs]
    else:
        return HttpResponseBadRequest('invalid query')

    result = {
        'items': ret,
        'more': page * count <= total,
    }

    return HttpResponse(json.dumps(result, ensure_ascii=False), content_type="application/json")


def get_api_key(request):
    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=401)
    if hasattr(request.user, 'api_key') and request.user.api_key is not None:
        api_key = request.user.api_key
    else:
        api_key = ApiKey.objects.create(user=request.user)
    return HttpResponse(api_key.key)


@login_required
def party_action(request, secret_key, action):
    party = get_object_or_404(Party.objects.for_user(request.user), secret_key=secret_key)
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

    has_statistics = Statistics.objects.filter(contest_id=OuterRef('pk'))
    party_contests = Contest.objects \
        .filter(rating__party=party) \
        .annotate(has_statistics=Exists(has_statistics)) \
        .order_by('-end_time')

    coders = party.coders.filter(
        account__resource__contest__rating__party=party,
        account__resource__contest__statistics__account=F('account')
    ).annotate(
        n_participations=Count('account__resource')
    ).order_by(
        '-n_participations'
    ).select_related(
        'user'
    )
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
