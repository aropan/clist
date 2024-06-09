from django.urls import re_path

from true_coders import views

app_name = 'coder'

urlpatterns = [
    re_path(r'^settings/$', views.settings, name='settings'),
    re_path(r'^settings/(?P<tab>preferences|social|accounts|filters|notifications|lists|calendars|subscriptions)/$',
            views.settings,
            name='settings'),
    re_path(r'^settings/notifications/unsubscribe/$', views.unsubscribe, name='unsubscribe'),
    re_path(r'^settings/change/$', views.change, name='change'),
    re_path(r'^settings/search/$', views.search, name='search'),
    re_path(r'^coder/$', views.my_profile, name='my_profile'),
    re_path(r'^coder/(?P<username>[^/]*)/ratings/$', views.ratings, name='ratings'),
    re_path(r'^coder/([^/]*)/$', views.profile, name='profile'),
    re_path(r'^coders/$', views.coders, name='coders'),
    re_path(r'^account/(?P<key>.*)/resource/(?P<host>.*)/ratings/$', views.ratings),
    re_path(
        r'^account/(?P<key>.*)/resource/(?P<host>.*)/verification/$',
        views.account_verification,
        name='account_verification',
    ),
    re_path(r'^account/(?P<key>.*)/resource/(?P<host>.*)/$', views.account, name='account'),
    re_path(r'^accounts/$', views.accounts, name='accounts'),
    re_path(r'^profile/(?P<query>.*)/ratings/$', views.ratings),
    re_path(r'^profile/(?P<query>.*)/$', views.profiles, name='mixed_profile'),
    re_path(r'^team/(?P<query>.*)/$', views.team, name='coders_team'),
    re_path(r'^api/key/$', views.get_api_key, name='api-key'),
    re_path(r'^remove/api/key/$', views.remove_api_key, name='remove-api-key'),
    re_path(r'^party/([^/]*)/(join|leave)/$', views.party_action, name='party-action'),
    re_path(r'^party/([^/]*)/contests/$', views.party_contests, name='party-contests'),
    re_path(r'^party/([^/]*)/(?:(calendar|ranking|information)/)?$', views.party, name='party'),
    re_path(r'^parties/$', views.parties, name='parties'),
    re_path(r'^list/([^/]*)/$', views.view_list, name='list'),
    re_path(r'^promotion/skip/$', views.skip_promotion, name='skip-promotion'),
]
