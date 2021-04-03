#!/usr/bin/env python3

from django.urls import path

from chats import views

app_name = 'chats'

urlpatterns = [
    path('chats/', views.index, name='index'),
]
