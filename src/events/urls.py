from django.urls import re_path

from events import views

app_name = 'events'

urlpatterns = [
    re_path(r'^events/$', views.events, name='events'),
    re_path(r'^event/(?P<slug>[\w-]+)/$', views.event, name='event'),
    re_path(r'^event/(?P<slug>[\w-]+)/result/(?P<name>[^/]+)/$', views.result, name='result'),
    re_path(r'^event/(?P<slug>[\w-]+)/change/$', views.change, name='change'),
    re_path(r'^event/(?P<slug>[\w-]+)/search/$', views.search, name='search'),
    re_path(r'^event/(?P<slug>[\w-]+)/team-details/(?P<team_id>[0-9]+)/$', views.team_admin_view, name='team-details'),
    re_path(r'^event/(?P<slug>[\w-]+)/frame/teams/(?P<status>[-\s\w]+)/$', views.frame, name='frame'),
    re_path(r'^event/(?P<slug>[\w-]+)/(?P<tab>[\w-]+)/$', views.event, name='event-tab'),
]
