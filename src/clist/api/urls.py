from django.conf.urls import include
from django.urls import re_path
from tastypie.api import NamespacedApi as Api

from clist.api import v1, v2, v3, v4

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

api_v3 = Api(api_name='v3', urlconf_namespace=f'{app_name}:api:v3')
api_v3.register(v3.ResourceResource())
api_v3.register(v3.ContestResource())
api_v3.register(v3.AccountResource())
api_v3.register(v3.CoderResource())
api_v3.register(v3.StatisticsResource())

api_v4 = Api(api_name='v4', urlconf_namespace=f'{app_name}:api:v4')
api_v4.register(v4.ResourceResource())
api_v4.register(v4.ContestResource())
api_v4.register(v4.AccountResource())
api_v4.register(v4.CoderResource())
api_v4.register(v4.StatisticsResource())
api_v4.register(v4.ProblemResource())

apis = [api_v4, api_v3, api_v2, api_v1]

urlpatterns = []

for index, api in enumerate(apis):
    name = f'{api.api_name}_doc' if index else 'latest'
    urlpatterns += [
        re_path(r'', include((api.urls, app_name), namespace=api.api_name)),
        re_path(
            f'{api.api_name}/doc/',
            include(('tastypie_swagger.urls', app_name), namespace=name),
            kwargs={
                'version': api.api_name,
                'tastypie_api_module': api,
                'namespace': f'clist:api:{name}',
            },
        ),
    ]
