from django.conf.urls import url, include
from clist import views

from tastypie.api import NamespacedApi as Api
from clist.api import v1


app_name = 'clist'

api_v1 = Api(api_name="v1", urlconf_namespace=f'{app_name}:api')
api_v1.register(v1.ResourceResource())
api_v1.register(v1.ContestResource())

urlpatterns = [
    url(r'^$', views.main, name='main'),
    url(r'^send-event-notification/$', views.send_event_notification, name='send_event_notification'),
    url(r'^resources/$', views.resources, name='resources'),
    url(r'^resources/dumpdata/$', views.resources_dumpdata, name='resources_dumpdata'),
    url(r'^resource/(.*)/$', views.resource, name='resource'),
    url(r'^get/events/$', views.get_events),
    url(r'^problems/$', views.problems, name='problems'),

    url(r'^api/', include((api_v1.urls, app_name), namespace='api')),
    url(
        r'^api/v1/doc/',
        include(('tastypie_swagger.urls', app_name), namespace='tastypie_swagger'),
        kwargs={
            'version': '1.0',
            'tastypie_api_module': api_v1,
            'namespace': 'clist:tastypie_swagger',
        },
    ),
]
