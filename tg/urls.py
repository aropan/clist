from django.views.decorators.csrf import csrf_exempt
from django.conf.urls import url
from tg import views

import hashlib
from django.conf import settings


app_name = 'telegram'

urlpatterns = [
    url(r'^me/$', views.me, name='me'),
    url(r'^unlink/$', views.unlink, name='unlink'),
    url(
        r'^incoming/%s/$' % hashlib.md5(settings.TELEGRAM_TOKEN.encode('utf8')).hexdigest(),
        csrf_exempt(views.Incoming.as_view()),
        name='incoming',
    ),
]
