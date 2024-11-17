import json
import re

import arrow
from django.core.exceptions import FieldDoesNotExist
from django.db.models import CharField, IntegerField, JSONField, Value
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import F
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.urls import re_path, reverse
from django.utils.timezone import now
from tastypie import fields
from tastypie.exceptions import BadRequest
from tastypie.utils import trailing_slash

from clist.api.common import BaseModelResource as CommmonBaseModuelResource
from clist.api.common import is_true_value
from clist.api.paginator import EstimatedCountPaginator
from clist.api.serializers import ContestAtomSerializer, use_in_atom_format
from clist.models import Contest, Resource
from clist.templatetags.extras import format_time, hr_timedelta
from clist.templatetags.extras import timezone as set_timezone
from pyclist.context_processors import coder_time_info
from ranking.models import Account, Statistics
from true_coders.models import Coder, Filter
from utils.timetools import parse_duration


class BaseModelResource(CommmonBaseModuelResource):

    class Meta(CommmonBaseModuelResource.Meta):
        paginator_class = EstimatedCountPaginator

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        filters.pop('total_count', None)

        custom_filters = {}
        for filter_expr in list(filters):
            filter_bits = filter_expr.split(LOOKUP_SEP)
            field_name = filter_bits.pop(0)
            if field_name not in self.fields:
                continue
            try:
                django_field_name = self.fields[field_name].attribute
                self._meta.object_class._meta.get_field(django_field_name)
                continue
            except FieldDoesNotExist:
                pass
            filter_type = filter_bits.pop() if filter_bits else 'exact'
            lookup_bits = self.check_filtering(field_name, filter_type, filter_bits)
            value = self.filter_value_to_python(filters[filter_expr], field_name, filters, filter_expr, filter_type)
            db_field_name = LOOKUP_SEP.join(lookup_bits)
            qs_filter = "%s%s%s" % (db_field_name, LOOKUP_SEP, filter_type)
            custom_filters[qs_filter] = value
            filters.pop(filter_expr)

        filters = super().build_filters(filters, *args, **kwargs)

        filters.update(custom_filters)
        return filters

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('total_count', None)
        return bundle

    def apply_sorting(self, *args, **kwargs):
        ret = super().apply_sorting(*args, **kwargs)
        ordering = getattr(ret.query, 'order_by', None)
        if ordering:
            new_ordering = []
            for field in ordering:
                if field[0] == '-':
                    order = 'desc'
                    field = field[1:]
                else:
                    order = 'asc'
                new_ordering.append(getattr(F(field), order)(nulls_last=True))
            ret = ret.order_by(*new_ordering)
        return ret


class ResourceResource(BaseModelResource):
    name = fields.CharField('host')
    icon = fields.CharField('icon')
    short = fields.CharField('short_host', null=True)
    n_accounts = fields.IntegerField('n_accounts')
    n_contests = fields.IntegerField('n_contests')
    total_count = fields.BooleanField()
    url = fields.CharField('url', use_in=use_in_atom_format)

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Resource.objects.all()
        resource_name = 'resource'
        excludes = ('total_count', 'url')
        filtering = {
            'total_count': ['exact'],
            'id': ['exact', 'in'],
            'name': ['exact', 'in'],
            'short': ['exact', 'in'],
            'n_accounts': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_contests': ['exact', 'gt', 'lt', 'gte', 'lte'],
        }
        ordering = ['id', 'name', 'n_accounts', 'n_contests']

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data['icon'] = '/media/sizes/64x64/' + bundle.data['icon']
        return bundle


class ContestResource(BaseModelResource):
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    host = fields.CharField('host')
    event = fields.CharField('title')
    start = fields.DateTimeField('start_time')
    end = fields.DateTimeField('end_time')
    n_statistics = fields.IntegerField('n_statistics', null=True)
    n_problems = fields.IntegerField('n_problems', null=True)
    parsed_at = fields.DateTimeField('parsed_time', null=True)
    upcoming = fields.BooleanField(help_text='Boolean data (default true if format is atom). Filter upcoming contests')  # noqa
    format_time = fields.BooleanField(help_text='Boolean data (default true if format is atom). Convert time to user timezone and timeformat')  # noqa
    duration = fields.DateTimeField('duration_in_secs', help_text='Time delta: Ex: "864000" or "10 days"')
    href = fields.CharField('url')
    filtered = fields.BooleanField(help_text='Use user filters')
    category = fields.CharField(help_text=f'Category to filter (default: api, allowed {Filter.CATEGORIES})')
    problems = fields.CharField('problems', null=True, help_text='Dict or List data')
    with_problems = fields.BooleanField()
    total_count = fields.BooleanField()
    releated_resource = fields.ForeignKey(ResourceResource, 'resource', use_in=use_in_atom_format, full=True)
    updated = fields.DateTimeField('updated', use_in=use_in_atom_format)
    start_time = fields.DateTimeField('start_time', use_in=use_in_atom_format)
    start_time__during = fields.DateTimeField(help_text='Time delta: Ex: "864000" or "10 days" (default "1 day" if format is atom)')  # noqa
    end_time__during = fields.DateTimeField(help_text='Time delta: Ex: "864000" or "10 days"')

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Contest.visible.all()
        resource_name = 'contest'
        excludes = ('filtered', 'category', 'total_count', 'with_problems', 'upcoming', 'format_time',
                    'releated_resource', 'updated', 'start_time', 'start_time__during', 'end_time__during')
        filtering = {
            'total_count': ['exact'],
            'with_problems': ['exact'],
            'upcoming': ['exact'],
            'format_time': ['exact'],
            'start_time__during': ['exact'],
            'end_time__during': ['exact'],
            'id': ['exact', 'in'],
            'resource_id': ['exact', 'in'],
            'resource': ['exact', 'iregex', 'regex', 'in'],
            'host': ['exact', 'iregex', 'regex'],
            'event': ['exact', 'iregex', 'regex'],
            'start': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'end': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'parsed_at': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'duration': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_statistics': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'n_problems': ['exact', 'gt', 'lt', 'gte', 'lte'],
            'filtered': ['exact'],
            'category': ['exact'],
        }
        ordering = ['id', 'event', 'start', 'end', 'resource_id', 'duration', 'parsed_at']
        serializer = ContestAtomSerializer()

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('filtered')
        bundle.data.pop('category')

        bundle.data.pop('with_problems', None)
        problems = bundle.data.pop('problems')
        if problems:
            problems = json.loads(problems)
        bundle.data['problems'] = problems

        bundle.data.pop('upcoming', None)
        bundle.data.pop('format_time', None)
        bundle.data.pop('start_time__during', None)
        bundle.data.pop('end_time__during', None)

        format_time_info = getattr(bundle.obj, 'format_time_info', None)
        if format_time_info:
            start = set_timezone(arrow.get(bundle.data['start']), format_time_info['timezone'])
            bundle.data['start'] = format_time(start, format_time_info['timeformat'])
            end = set_timezone(arrow.get(bundle.data['end']), format_time_info['timezone'])
            bundle.data['end'] = format_time(end, format_time_info['timeformat'])
            bundle.data['duration'] = hr_timedelta(bundle.data['duration'])

        return bundle

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        upcoming = filters.pop('upcoming', None)
        filtered = filters.pop('filtered', None)
        category = filters.pop('category', ['api'])
        with_problems = filters.pop('with_problems', None)
        format_time = filters.pop('format_time', None)
        start_time__during = filters.pop('start_time__during', None)
        end_time__during = filters.pop('end_time__during', None)
        filters = super().build_filters(filters, *args, **kwargs)
        if filtered is not None:
            filters['filtered'] = filtered[-1]
            filters['category'] = category[-1]
        if upcoming:
            filters['upcoming'] = upcoming[-1]
        if with_problems:
            filters['with_problems'] = with_problems[-1]
        if format_time:
            filters['format_time'] = format_time[-1]
        if start_time__during:
            filters['start_time__during'] = start_time__during[-1]
        if end_time__during:
            filters['end_time__during'] = end_time__during[-1]
        return filters

    def apply_filters(self, request, applicable_filters):
        is_atom = request.GET.get('format') in ['atom', 'rss']
        for f in list(applicable_filters.keys()):
            if f.startswith('duration'):
                applicable_filters[f] = parse_duration(applicable_filters[f]).total_seconds()
        filtered = applicable_filters.pop('filtered', None)
        category = applicable_filters.pop('category', None)
        upcoming = applicable_filters.pop('upcoming', 'true' if is_atom else None)
        with_problems = applicable_filters.pop('with_problems', None)
        format_time = applicable_filters.pop('format_time', 'true' if is_atom else None)

        if is_atom and 'start_time__during' not in applicable_filters:
            applicable_filters['start_time__during'] = '1 day'

        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('resource')

        if filtered is not None and request.user:
            filter_ = request.user.coder.get_contest_filter([category])
            if not is_true_value(filtered):
                filter_ = ~filter_
            qs = qs.filter(filter_)

        if is_true_value(with_problems):
            qs = qs.annotate(problems=Cast(KeyTextTransform('problems', 'info'), CharField()))

        if is_true_value(format_time):
            time_info = coder_time_info(request)
            qs = qs.annotate(format_time_info=Value(time_info, JSONField()))

        if upcoming is not None:
            query = 'end_time__gt' if is_true_value(upcoming) else 'end_time__lte'
            qs = qs.filter(**{query: now()})

        return qs


class StatisticsResource(BaseModelResource):
    account_id = fields.IntegerField('account_id')
    handle = fields.CharField('account__key')
    contest_id = fields.IntegerField('contest_id')
    event = fields.CharField('contest__title')
    date = fields.DateTimeField('contest__end_time')
    coder_id = fields.IntegerField()
    place = fields.IntegerField('place_as_int', null=True)
    score = fields.FloatField('solving')
    new_rating = fields.IntegerField('new_rating', null=True)
    old_rating = fields.IntegerField('old_rating', null=True)
    rating_change = fields.IntegerField('rating_change', null=True)
    problems = fields.DictField('problems', null=True)
    more_fields = fields.DictField('more_fields', null=True)
    with_problems = fields.BooleanField()
    with_more_fields = fields.BooleanField()
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Statistics.objects.all()
        resource_name = 'statistics'
        excludes = ('total_count', 'with_problems', 'with_more_fields', 'coder_id')
        filtering = {
            'total_count': ['exact'],
            'with_problems': ['exact'],
            'with_more_fields': ['exact'],
            'contest_id': ['exact', 'in'],
            'account_id': ['exact', 'in'],
            'coder_id': ['exact'],
            'place': ['exact', 'isnull'],
            'new_rating': ['isnull'],
            'rating_change': ['isnull'],
        }
        ordering = ['score', 'place', 'new_rating', 'rating_change', 'date']
        detail_allowed_methods = []

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        tmp = {}
        for k in 'new_rating__isnull', 'rating_change__isnull', 'coder_id', 'with_problems', 'with_more_fields':
            val = filters.pop(k, None)
            if val:
                tmp[k] = val[0]
        filters = super().build_filters(filters, *args, **kwargs)
        filters.update(tmp)
        return filters

    def apply_filters(self, request, applicable_filters):
        one_of = ['contest_id__exact', 'contest_id__in', 'account_id__exact', 'account_id__in', 'coder_id']
        for k in one_of:
            if applicable_filters.get(f'{k}'):
                break
        else:
            raise BadRequest(f'One of {[k.split("__")[0] for k in one_of]} is required')

        rating_change_isnull = applicable_filters.pop('rating_change__isnull', None)
        new_rating_isnull = applicable_filters.pop('new_rating__isnull', None)
        coder_id = applicable_filters.pop('coder_id', None)
        with_problems = applicable_filters.pop('with_problems', None)
        with_more_fields = applicable_filters.pop('with_more_fields', None)

        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('account', 'contest')

        if rating_change_isnull is not None:
            qs = qs.filter(addition__rating_change__isnull=is_true_value(rating_change_isnull))
        if new_rating_isnull is not None:
            qs = qs.filter(addition__new_rating__isnull=is_true_value(new_rating_isnull))
        if coder_id is not None:
            qs = qs.filter(account__coders=coder_id)

        qs = qs \
            .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
            .annotate(old_rating=Cast(KeyTextTransform('old_rating', 'addition'), IntegerField())) \
            .annotate(rating_change=Cast(KeyTextTransform('rating_change', 'addition'), IntegerField()))

        if is_true_value(with_problems):
            qs = qs.annotate(problems=Cast(KeyTextTransform('problems', 'addition'), JSONField()))

        if is_true_value(with_more_fields):
            qs = qs.annotate(more_fields=Cast(F('addition'), JSONField()))

        return qs

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('coder_id', None)
        bundle.data.pop('with_problems', None)
        bundle.data.pop('with_more_fields', None)

        problems = bundle.data['problems']
        if problems:
            for problem in problems.values():
                for k in list(problem.keys()):
                    if k.startswith('_'):
                        problem.pop(k, None)
                for k in 'solution', 'external_solution':
                    problem.pop(k, None)

        more_fields = bundle.data['more_fields']
        if more_fields:
            for k in list(more_fields.keys()):
                if k.startswith('_') or k in bundle.data:
                    more_fields.pop(k, None)
            for k in 'problems', 'solved':
                more_fields.pop(k, None)
        return bundle


class AccountResource(BaseModelResource):
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    handle = fields.CharField('key')
    name = fields.CharField('name', null=True)
    rating = fields.IntegerField('rating', null=True)
    overall_rank = fields.IntegerField('resource_rank', null=True)
    n_contests = fields.IntegerField('n_contests')
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Account.objects.all()
        resource_name = 'account'
        excludes = ('total_count', )
        filtering = {
            'total_count': ['exact'],
            'id': ['exact', 'in'],
            'resource_id': ['exact', 'in'],
            'resource': ['exact', 'iregex', 'regex', 'in'],
            'handle': ['exact', 'in'],
            'rating': ['exact', 'gt', 'lt', 'gte', 'lte', 'isnull'],
            'overall_rank': ['exact', 'gt', 'lt', 'gte', 'lte', 'isnull'],
        }
        ordering = ['id', 'handle', 'rating', 'overall_rank', 'n_contests']

    def apply_filters(self, request, applicable_filters):
        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('resource')
        return qs


def get_api_version(bundle):
    parts = bundle.request.path.split('/')
    for part in parts:
        if re.match('^v[0-9]+$', part):
            return part
    return None


def use_in_me_only(bundle, *args, **kwargs):
    api_version = get_api_version(bundle)
    url = reverse(f'clist:api:{api_version}:api_dispatch_me',
                  kwargs={'api_name': api_version, 'resource_name': 'coder'})
    return url == bundle.request.path


def use_in_detail_only(bundle, *args, **kwargs):
    with_accounts = is_true_value(bundle.request.GET.get('with_accounts'))
    query_by_id = bool(bundle.request.GET.get('id') or bundle.request.GET.get('username'))
    api_version = get_api_version(bundle)
    url = reverse(f'clist:api:{api_version}:api_dispatch_list',
                  kwargs={'api_name': api_version, 'resource_name': 'coder'})
    return with_accounts or query_by_id or not (url == bundle.request.path or use_in_me_only(bundle, *args, **kwargs))


class CoderResource(BaseModelResource):
    username = fields.CharField('username')
    first_name = fields.CharField('user__first_name')
    last_name = fields.CharField('user__last_name')
    country = fields.CharField('country')
    timezone = fields.CharField('timezone', use_in=use_in_me_only)
    email = fields.CharField('user__email', use_in=use_in_me_only)
    n_accounts = fields.IntegerField('n_accounts', use_in='list')
    accounts = fields.ManyToManyField(AccountResource, 'account_set', use_in=use_in_detail_only, full=True)
    with_accounts = fields.BooleanField()
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        object_class = Coder
        queryset = Coder.objects.all()
        resource_name = 'coder'
        excludes = ('total_count', 'with_accounts')
        filtering = {
            'total_count': ['exact'],
            'with_accounts': ['exact'],
            'country': ['exact'],
            'id': ['exact', 'in'],
            'username': ['exact', 'in'],
        }
        extra_actions = [
            {
                'name': 'me',
                'summary': 'Retrieve your coder',
                'resource_type': 'list',
                'responseClass': 'coder',
            }
        ]
        ordering = ['n_accounts']

    def me(self, request, *args, **kwargs):
        kwargs['me'] = True
        return self.dispatch('detail', request, **kwargs)

    def prepend_urls(self):
        return [
            re_path(
                r'^(?P<resource_name>%s)/me%s$' % (self._meta.resource_name, trailing_slash),
                self.wrap_view('me'),
                name='api_dispatch_me'
            )
        ]

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        for k in self.fields.keys():
            if k in bundle.data and not bundle.data[k] and isinstance(bundle.data[k], str):
                bundle.data[k] = None
        bundle.data.pop('with_accounts', None)
        return bundle

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        me = filters.pop('me', None)
        filters.pop('with_accounts', None)
        filters = super().build_filters(filters, *args, **kwargs)
        filters['me'] = me
        return filters

    def apply_filters(self, request, applicable_filters):
        me = applicable_filters.pop('me', None)
        qs = super().apply_filters(request, applicable_filters)
        if me:
            qs = qs.filter(pk=request.user.coder.pk)
        qs = qs.select_related('user')

        fake_bundle = type('obj', (object,), {'request': request})
        if use_in_detail_only(fake_bundle):
            qs = qs.prefetch_related('account_set__resource')
        return qs
