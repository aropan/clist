from django.conf.urls import url, include
from tastypie.api import NamespacedApi as Api
from clist.api import v1
from clist.api import v2

app_name = 'clist'

api_v1 = Api(api_name='v1', urlconf_namespace=f'{app_name}:api:v1')
api_v1.register(v1.ResourceResource())
api_v1.register(v1.ContestResource())

api_v2 = Api(api_name='v2', urlconf_namespace=f'{app_name}:api:v2')
api_v2.register(v2.ResourceResource())
api_v2.register(v2.ContestResource())
api_v2.register(v2.AccountResource())
api_v2.register(v2.CoderResource())
api_v2.register(v2.StatisticsResource())

apis = [api_v2, api_v1]

urlpatterns = []

for index, api in enumerate(apis):
    name = f'{api.api_name}_doc' if index else 'latest'
    urlpatterns += [
        url(r'', include((api.urls, app_name), namespace=api.api_name)),
        url(
            f'{api.api_name}/doc/',
            include(('tastypie_swagger.urls', app_name), namespace=name),
            kwargs={
                'version': api.api_name,
                'tastypie_api_module': api,
                'namespace': f'clist:api:{name}',
            },
        ),
    ]
