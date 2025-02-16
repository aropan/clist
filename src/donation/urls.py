from django.urls import re_path

from donation import views

app_name = 'donation'

urlpatterns = [
    re_path(r'^donate/$', views.donate, name='donate'),
]
