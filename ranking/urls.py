from django.conf.urls import url

from ranking import views


app_name = 'ranking'

urlpatterns = [
    url(r'^party/(.*)/ranking/$', views.party_ranking, name='party'),
]
