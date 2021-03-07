from django.conf.urls import re_path
from true_coders import views


app_name = 'coder'

urlpatterns = [
    re_path(r'^settings/$', views.settings, name='settings'),
    re_path(r'^settings/(preferences|social|accounts|filters|notifications)/$', views.settings, name='settings'),
    re_path(r'^settings/notifications/unsubscribe/$', views.unsubscribe, name='unsubscribe'),
    re_path(r'^settings/change/$', views.change, name='change'),
    re_path(r'^settings/search/$', views.search, name='search'),
    re_path(r'^coder/$', views.coder_profile, name='coder_profile'),
    re_path(r'^coder/([^/]*)/$', views.profile, name='profile'),
    re_path(r'^coder/(?P<username>[^/]*)/ratings/$', views.ratings, name='ratings'),
    re_path(r'^coders/$', views.coders, name='coders'),
    re_path(r'^account/(?P<key>.*)/resource/(?P<host>.*)/ratings/$', views.ratings),
    re_path(r'^account/(?P<key>.*)/resource/(?P<host>.*)/$', views.account, name='account'),
    re_path(r'^api/key/$', views.get_api_key, name='api-key'),
    re_path(r'^remove/api/key/$', views.remove_api_key, name='remove-api-key'),
    re_path(r'^party/([^/]*)/(join|leave)/$', views.party_action, name='party-action'),
    re_path(r'^party/([^/]*)/contests/$', views.party_contests, name='party-contests'),
    re_path(r'^party/([^/]*)/(?:(calendar|ranking|information)/)?$', views.party, name='party'),
    re_path(r'^parties/$', views.parties, name='parties'),
]
