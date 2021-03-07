from django.conf.urls import url
from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db.models import IntegerField
from django.db.models.functions import Cast
from django.urls import reverse
from pytimeparse.timeparse import timeparse
from tastypie import fields
from tastypie.exceptions import BadRequest
from tastypie.utils import trailing_slash

from clist.api.common import BaseModelResource as CommmonBaseModuelResource
from clist.api.paginator import EstimatedCountPaginator
from clist.models import Contest, Resource
from ranking.models import Account, Statistics
from true_coders.models import Coder, Filter


class BaseModelResource(CommmonBaseModuelResource):

    class Meta(CommmonBaseModuelResource.Meta):
        paginator_class = EstimatedCountPaginator

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        filters.pop('total_count', None)
        return super().build_filters(filters, *args, **kwargs)

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('total_count', None)
        return bundle


class ResourceResource(BaseModelResource):
    name = fields.CharField('host')
    icon = fields.CharField('icon')
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Resource.objects.all()
        resource_name = 'resource'
        excludes = ('total_count', )
        filtering = {
            'total_count': ['exact'],
            'id': ['exact', 'in'],
            'name': ['exact', 'iregex', 'regex', 'in'],
        }
        ordering = ['id', 'name', ]

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data['icon'] = '/imagefit/static_resize/64x64/' + bundle.data['icon']
        return bundle


class ContestResource(BaseModelResource):
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    event = fields.CharField('title')
    start = fields.DateTimeField('start_time')
    end = fields.DateTimeField('end_time')
    duration = fields.DateTimeField('duration_in_secs', help_text='Time delta: Ex: "864000" or "10 days"')
    href = fields.CharField('url')
    filtered = fields.BooleanField(help_text='Use user filters')
    category = fields.CharField(help_text=f'Category to filter (default: api, allowed {Filter.CATEGORIES})')
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Contest.visible.all()
        resource_name = 'contest'
        excludes = ('filtered', 'category', 'total_count', )
        filtering = {
            'total_count': ['exact'],
            'id': ['exact', 'in'],
            'resource_id': ['exact', 'in'],
            'resource': ['exact'],
            'event': ['exact', 'iregex', 'regex'],
            'start': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'end': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'duration': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'filtered': ['exact'],
            'category': ['exact'],
        }
        ordering = ['id', 'event', 'start', 'end', 'resource_id', 'duration']

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('filtered')
        bundle.data.pop('category')
        return bundle

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        filtered = filters.pop('filtered', None)
        category = filters.pop('category', 'api')
        resource = filters.pop('resource', None)
        filters = super().build_filters(filters, *args, **kwargs)
        if filtered is not None:
            filters['filtered'] = filtered[-1]
            filters['category'] = category[-1]
        if resource:
            filters['resource__host'] = resource[-1]
        return filters

    def apply_filters(self, request, applicable_filters):
        filtered = None
        category = 'api'
        for f in list(applicable_filters.keys()):
            if f.startswith('duration'):
                v = applicable_filters.pop(f)
                v = int(v) if v.isdigit() else timeparse(v)
                applicable_filters[f] = v
            elif f == 'filtered':
                filtered = applicable_filters.pop(f).lower() in ['true', 'yes', '1']
            elif f == 'category':
                category = applicable_filters.pop(f)

        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('resource')

        if filtered is not None and request.user:
            filter_ = request.user.coder.get_contest_filter([category])
            if not filtered:
                filter_ = ~filter_
            qs = qs.filter(filter_)

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
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Statistics.objects.all()
        resource_name = 'statistics'
        excludes = ('total_count', )
        filtering = {
            'total_count': ['exact'],
            'contest_id': ['exact'],
            'account_id': ['exact'],
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
        for k in 'new_rating__isnull', 'rating_change__isnull', 'coder_id':
            tmp[k] = filters.pop(k, None)
        filters = super().build_filters(filters, *args, **kwargs)
        filters.update(tmp)
        return filters

    def apply_filters(self, request, applicable_filters):
        one_of = ['contest_id__exact', 'account_id__exact', 'coder_id']
        for k in one_of:
            if applicable_filters.get(f'{k}'):
                break
        else:
            raise BadRequest(f'One of {[k.split("__")[0] for k in one_of]} is required')

        rating_change_isnull = applicable_filters.pop('rating_change__isnull', None)
        new_rating_isnull = applicable_filters.pop('new_rating__isnull', None)
        coder_id = applicable_filters.pop('coder_id', None)

        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('account', 'contest')

        if rating_change_isnull:
            qs = qs.filter(addition__rating_change__isnull=rating_change_isnull[0] in ['true', '1', 'yes'])
        if new_rating_isnull:
            qs = qs.filter(addition__new_rating__isnull=new_rating_isnull[0] in ['true', '1', 'yes'])
        if coder_id:
            qs = qs.filter(account__coders=coder_id[0])

        qs = qs \
            .annotate(new_rating=Cast(KeyTextTransform('new_rating', 'addition'), IntegerField())) \
            .annotate(old_rating=Cast(KeyTextTransform('old_rating', 'addition'), IntegerField())) \
            .annotate(rating_change=Cast(KeyTextTransform('rating_change', 'addition'), IntegerField()))

        return qs

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data.pop('coder_id', None)
        return bundle


class AccountResource(BaseModelResource):
    resource = fields.CharField('resource__host')
    resource_id = fields.IntegerField('resource_id')
    handle = fields.CharField('key')
    name = fields.CharField('name', null=True)
    rating = fields.IntegerField('rating', null=True)
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
            'resource': ['exact'],
            'handle': ['exact', 'iregex', 'regex'],
            'rating': ['exact', 'gt', 'lt', 'gte', 'lte', 'isnull'],
        }
        ordering = ['id', 'handle', 'rating', 'n_contests']

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        resource = filters.pop('resource', None)
        filters = super().build_filters(filters, *args, **kwargs)
        if resource:
            filters['resource__host'] = resource[-1]
        return filters

    def apply_filters(self, request, applicable_filters):
        qs = super().apply_filters(request, applicable_filters)
        qs = qs.select_related('resource')
        return qs


def use_in_me_only(bundle, *args, **kwargs):
    url = reverse('clist:api:v2:api_dispatch_me', kwargs={'api_name': 'v2', 'resource_name': 'coder'})
    return url == bundle.request.path


def use_in_detail_only(bundle, *args, **kwargs):
    url = reverse('clist:api:v2:api_dispatch_list', kwargs={'api_name': 'v2', 'resource_name': 'coder'})
    return not (url == bundle.request.path or use_in_me_only(bundle, *args, **kwargs))


class CoderResource(BaseModelResource):
    username = fields.CharField('username')
    first_name = fields.CharField('user__first_name')
    last_name = fields.CharField('user__last_name')
    country = fields.CharField('country')
    timezone = fields.CharField('timezone', use_in=use_in_me_only)
    email = fields.CharField('user__email', use_in=use_in_me_only)
    n_accounts = fields.IntegerField('n_accounts', use_in='list')
    accounts = fields.ManyToManyField(AccountResource, 'account_set', use_in=use_in_detail_only, full=True)
    total_count = fields.BooleanField()

    class Meta(BaseModelResource.Meta):
        abstract = False
        object_class = Coder
        queryset = Coder.objects.all()
        resource_name = 'coder'
        excludes = ('total_count')
        filtering = {
            'total_count': ['exact'],
            'country': ['exact'],
            'username': ['exact', 'iregex', 'regex']
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
            url(
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
        return bundle

    def build_filters(self, filters=None, *args, **kwargs):
        filters = filters or {}
        me = filters.pop('me', None)
        filters = super().build_filters(filters, *args, **kwargs)
        filters['me'] = me
        return filters

    def apply_filters(self, request, applicable_filters):
        me = applicable_filters.pop('me', None)
        qs = super().apply_filters(request, applicable_filters)
        if me:
            qs = qs.filter(pk=request.user.coder.pk)
        qs = qs.select_related('user')

        url = reverse('clist:api:v2:api_dispatch_list',
                      kwargs={'api_name': 'v2', 'resource_name': self._meta.resource_name})
        if url != request.path:
            qs = qs.prefetch_related('account_set__resource')
        return qs
