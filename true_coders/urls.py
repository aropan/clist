from django.conf.urls import url
from true_coders import views


app_name = 'coder'

urlpatterns = [
    url(r'^settings/$', views.settings, name='settings'),
    url(r'^settings/change/$', views.change, name='change'),
    url(r'^settings/search/$', views.search, name='search'),
    url(r'^coder/([^/]*)/$', views.profile, name='profile'),
    url(r'^api/key/$', views.get_api_key, name='api-key'),
    url(r'^party/([^/]*)/(join|leave)/$', views.party_action, name='party-action'),
    url(r'^party/([^/]*)/contests/$', views.party_contests, name='party-contests'),
    url(r'^party/([^/]*)/(?:(calendar|ranking|information)/)?$', views.party, name='party'),
    url(r'^parties/$', views.parties, name='parties'),
]
