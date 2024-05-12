from django.urls import re_path

from submissions import views

app_name = 'submissions'

urlpatterns = [
    re_path(r'^submissions/(?P<title_slug>[^/]*)-(?P<contest_id>[0-9]+)/$', views.submissions, name='submissions'),
    re_path(r'^submissions/(?P<contest_id>[0-9]+)/$', views.submissions, name='submissions_by_id'),
    re_path(r'^submissions/(?P<title_slug>[^/]+)/$', views.submissions, name='submissions_by_slug'),
]
