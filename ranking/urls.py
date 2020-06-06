from django.conf.urls import url

from ranking import views


app_name = 'ranking'

urlpatterns = [
    url(r'^standings/$', views.standings_list, name='standings_list'),
    url(r'^standings/action/$', views.action, name='standings_action'),
    url(r'^standings/(?P<title_slug>[^/]+)-(?P<contest_id>[0-9]+)/$', views.standings, name='standings'),
    url(r'^standings/(?P<contest_id>[0-9]+)/$', views.standings, name='standings_by_id'),
    url(r'^standings/(?P<title_slug>[^/]+)/$', views.standings, name='standings_by_slug'),
    url(r'^solutions/(?P<sid>[0-9]+)/(?P<problem_key>.*)/$', views.solutions, name='solution'),
]
