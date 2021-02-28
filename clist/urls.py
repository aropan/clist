from django.conf.urls import url, include
from clist import views

app_name = 'clist'

urlpatterns = [
    url(r'^$', views.main, name='main'),
    url(r'^send-event-notification/$', views.send_event_notification, name='send_event_notification'),
    url(r'^resources/$', views.resources, name='resources'),
    url(r'^resources/dumpdata/$', views.resources_dumpdata, name='resources_dumpdata'),
    url(r'^resource/(.*)/$', views.resource, name='resource'),
    url(r'^get/events/$', views.get_events),
    url(r'^problems/$', views.problems, name='problems'),
    url(r'^api/', include('clist.api.urls', namespace='api')),
]
