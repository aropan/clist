from django.conf.urls import re_path
from my_oauth import views

app_name = 'auth'

urlpatterns = [
    re_path(r'^login/$', views.login, name='login'),
    re_path(r'^signup/$', views.signup, name='signup'),
    re_path(r'^logout/$', views.logout, name='logout'),
    re_path(r'^auth/services/dumpdata/$', views.services_dumpdata, name='services_dumpdata'),
    re_path(r'^oauth/([a-z]+)/$', views.query, name='query'),
    re_path(r'^oauth/([a-z]+)/unlink/$', views.unlink, name='unlink'),
    re_path(r'^oauth/([a-z]+)/response/$', views.response, name='response'),
]
