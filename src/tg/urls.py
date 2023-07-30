import hashlib

from django.conf import settings
from django.urls import re_path
from django.views.decorators.csrf import csrf_exempt

from tg import views

app_name = 'telegram'

urlpatterns = [
    re_path(r'^me/$', views.me, name='me'),
    re_path(r'^unlink/$', views.unlink, name='unlink'),
]

if settings.TELEGRAM_TOKEN is not None:
    urlpatterns += [
        re_path(
            r'^incoming/%s/$' % hashlib.md5(settings.TELEGRAM_TOKEN.encode('utf8')).hexdigest(),
            csrf_exempt(views.Incoming.as_view()),
            name='incoming',
        ),
    ]
