from pytimeparse.timeparse import timeparse
from tastypie import fields
from tastypie.resources import ALL_WITH_RELATIONS

from clist.models import Resource, Contest
from true_coders.models import Filter
from clist.api.common import BaseModelResource


class ResourceResource(BaseModelResource):
    name = fields.CharField('host')
    icon = fields.CharField('icon')

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Resource.objects.all()
        resource_name = 'resource'
        filtering = {
            'id': ['exact', 'in'],
            'name': ['exact', 'iregex', 'regex', 'in'],
        }
        ordering = ['id', 'name', ]

    def dehydrate(self, *args, **kwargs):
        bundle = super().dehydrate(*args, **kwargs)
        bundle.data['icon'] = '/media/sizes/64x64/' + bundle.data['icon']
        return bundle


class ContestResource(BaseModelResource):
    resource = fields.ForeignKey(ResourceResource, 'resource', full=True)
    event = fields.CharField('title')
    start = fields.DateTimeField('start_time')
    end = fields.DateTimeField('end_time')
    duration = fields.DateTimeField('duration_in_secs', help_text='Time delta: Ex: "864000" or "10 days"')
    href = fields.CharField('url')
    filtered = fields.BooleanField(help_text='Use user filters')
    category = fields.CharField(help_text=f'Category to filter (default: api, allowed {Filter.CATEGORIES})')

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Contest.visible.all()
        resource_name = 'contest'
        excludes = ('filtered', 'category', )
        filtering = {
            'id': ['exact', 'in'],
            'resource': ALL_WITH_RELATIONS,
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

        filters = super().build_filters(filters, *args, **kwargs)

        if filtered is not None:
            filters['filtered'] = filtered[-1]
            filters['category'] = category[-1]

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

        query_set = super().apply_filters(request, applicable_filters)

        if filtered is not None and request.user:
            filter_ = request.user.coder.get_contest_filter([category])
            if not filtered:
                filter_ = ~filter_
            query_set = query_set.filter(filter_)

        query_set = query_set.select_related('resource')

        return query_set
