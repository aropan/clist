from django.http import HttpResponse
from tastypie import fields, http
from tastypie.resources import NamespacedModelResource as ModelResource
from tastypie.authentication import ApiKeyAuthentication, SessionAuthentication, MultiAuthentication
from tastypie_oauth.authentication import OAuth2ScopedAuthentication
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
        include_absolute_url = False
        allowed_methods = ['get']
        fields = ['id']

        throttle = CacheThrottle(throttle_at=10, timeframe=60)

        authentication = MultiAuthentication(
            ApiKeyAuthentication(),
            SessionAuthentication(),
            OAuth2ScopedAuthentication(
                post=('read write', ),
                get=('read', ),
                put=('read', 'write'),
            ),
        )

    def _handle_500(self, request, exception):
        data = {'error_message': str(exception)}
        return self.error_response(request, data, response_class=http.HttpApplicationError)
