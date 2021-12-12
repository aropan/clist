from django.conf.urls import re_path

from notification import views

app_name = 'notification'

urlpatterns = [
    re_path(r'^calendar/(?P<uuid>[^/]*)/$', views.EventFeed(), name='calendar'),
]
