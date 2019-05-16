from django.conf.urls import url

from events import views


app_name = 'events'

urlpatterns = [
    url(r'^events/$', views.events, name='events'),
    url(r'^event/(?P<slug>[\w-]+)/$', views.event, name='event'),
    url(r'^event/(?P<slug>[\w-]+)/result/(?P<name>[\w-]+)/$', views.result, name='result'),
    url(r'^event/(?P<slug>[\w-]+)/change/$', views.change, name='change'),
    url(r'^event/(?P<slug>[\w-]+)/search/$', views.search, name='search'),
    url(r'^event/(?P<slug>[\w-]+)/team-details/(?P<team_id>[0-9]+)/$', views.team_admin_view, name='team-details'),
    url(r'^event/(?P<slug>[\w-]+)/frame/teams/(?P<status>[-\s\w]+)/$', views.frame, name='frame'),
]
