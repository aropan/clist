from django.views.decorators.csrf import csrf_exempt
from django.conf.urls import re_path
from tg import views

import hashlib
from django.conf import settings


app_name = 'telegram'

urlpatterns = [
    re_path(r'^me/$', views.me, name='me'),
    re_path(r'^unlink/$', views.unlink, name='unlink'),
    re_path(
        r'^incoming/%s/$' % hashlib.md5(settings.TELEGRAM_TOKEN.encode('utf8')).hexdigest(),
        csrf_exempt(views.Incoming.as_view()),
        name='incoming',
    ),
]
