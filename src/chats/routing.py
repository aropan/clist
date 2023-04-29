#!/usr/bin/env python3

from django.urls import re_path

from chats import consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/$', consumers.ChatConsumer.as_asgi()),
]
