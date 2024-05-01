from django.conf.urls import include
from django.urls import re_path
from django.views.generic import TemplateView

from clist import views

app_name = 'clist'

urlpatterns = [
    re_path(r'^$', views.main, name='main'),
    re_path(r'^send-event-notification/$', views.send_event_notification, name='send_event_notification'),
    re_path(r'^resources/$', views.resources, name='resources'),
    re_path(r'^resources/account/ratings/$', views.resources_account_ratings, name='resources_account_ratings'),
    re_path(r'^resources/country/ratings/$', views.resources_country_ratings, name='resources_country_ratings'),
    re_path(r'^resources/dumpdata/$', views.resources_dumpdata, name='resources_dumpdata'),
    re_path(r'^resource/(.*)/$', views.resource, name='resource'),
    re_path(r'^get/events/$', views.get_events),
    re_path(r'^problems/$', views.problems, name='problems'),
    re_path(r'^api/', include('clist.api.urls', namespace='api')),
    re_path(r'^donate/$', TemplateView.as_view(template_name='donate.html'), name='donate'),
    re_path(r'^links/$', TemplateView.as_view(template_name='links.html'), name='links'),

]
