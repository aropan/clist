from django.urls import re_path

from ranking import consumers

websocket_urlpatterns = [
    re_path(r'ws/contest/$', consumers.ContestConsumer.as_asgi()),
]
