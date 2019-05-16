from django.conf.urls import url
from my_oauth import views

app_name = 'auth'

urlpatterns = [
    url(r'^login/$', views.login, name='login'),
    url(r'^signup/$', views.signup, name='signup'),
    url(r'^logout/$', views.logout, name='logout'),
    url(r'^oauth/([a-z]+)/$', views.query, name='query'),
    url(r'^oauth/([a-z]+)/response/$', views.response, name='response'),
]
