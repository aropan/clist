from clist.models import Resource, Contest
from django.http import HttpResponse
from pytimeparse.timeparse import timeparse
from tastypie import fields, http
from tastypie.resources import NamespacedModelResource as ModelResource, ALL_WITH_RELATIONS
from tastypie.authentication import ApiKeyAuthentication, SessionAuthentication, MultiAuthentication
from tastypie.throttle import CacheThrottle


def build_content_type(format, encoding='utf-8'):
    '''
    Appends character encoding to the provided format if not already present.
    '''
    if 'charset' in format:
        return format
    return '%s; charset=%s' % (format, encoding)


class BaseModelResource(ModelResource):
    id = fields.IntegerField('id')

    def create_response(
        self,
        request,
        data,
        response_class=HttpResponse,
        **response_kwargs
    ):
        '''
        Extracts the common 'which-format/serialize/return-response' cycle.
        Mostly a useful shortcut/hook.
        '''
        desired_format = self.determine_format(request)
        serialized = self.serialize(request, data, desired_format)
        return response_class(
            content=serialized,
            content_type=build_content_type(desired_format),
            **response_kwargs
        )

    class Meta:
        abstract = True
        limit = 100
        include_resource_uri = False
        allowed_methods = ['get']
        fields = ['id', ]

        throttle = CacheThrottle(throttle_at=10, timeframe=60)

        authentication = MultiAuthentication(ApiKeyAuthentication(), SessionAuthentication())

    def _handle_500(self, request, exception):
        data = {'error_message': str(exception)}
        return self.error_response(request, data, response_class=http.HttpApplicationError)


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

    def dehydrate(self, bundle):
        bundle.data['icon'] = '/imagefit/static_resize/64x64/' + bundle.data['icon']
        return bundle


class ContestResource(BaseModelResource):
    resource = fields.ForeignKey(ResourceResource, 'resource', full=True)
    event = fields.CharField('title')
    start = fields.DateTimeField('start_time')
    end = fields.DateTimeField('end_time')
    duration = fields.DateTimeField(
        'duration_in_secs',
        help_text='Time delta: Ex: "864000" or "10 days"',
    )
    href = fields.CharField('url')
    filtered = fields.BooleanField(help_text='value of filters users')

    class Meta(BaseModelResource.Meta):
        abstract = False
        queryset = Contest.visible.all()
        resource_name = 'contest'
        excludes = ('filtered', )
        filtering = {
            'id': ['exact', 'in'],
            'resource': ALL_WITH_RELATIONS,
            'event': ['exact', 'iregex', 'regex'],
            'start': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'end': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'duration': ['exact', 'gt', 'lt', 'gte', 'lte', 'week_day'],
            'filtered': ['exact'],
        }
        # used in telegram filter
        ordering = ['id', 'event', 'start', 'end', 'resource', 'duration', 'href', ]

    def dehydrate(self, bundle):
        bundle.data.pop('filtered')
        return bundle

    def build_filters(self, filters=None, **kw):
        filters = filters or {}

        filtered = None
        if 'filtered' in filters:
            filtered = filters.pop('filtered')

        filters = super(ContestResource, self).build_filters(filters, **kw)

        if filtered is not None:
            filters['filtered'] = filtered[-1]

        return filters

    def apply_filters(self, request, applicable_filters):
        filtered = None
        for f in list(applicable_filters.keys()):
            if f.startswith('duration'):
                v = applicable_filters.pop(f)
                v = int(v) if v.isdigit() else timeparse(v)
                applicable_filters[f] = v
            if f == 'filtered':
                filtered = applicable_filters.pop(f).lower() in ['true', 'yes', '1']

        query_set = super(ContestResource, self).apply_filters(request, applicable_filters)

        if filtered is not None and request.user:
            filter_ = request.user.coder.get_contest_filter(['api'])
            if not filtered:
                filter_ = ~filter_
            query_set = query_set.filter(filter_)

        return query_set
