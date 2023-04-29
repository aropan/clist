from django.urls import path

from chats import views

app_name = 'chats'

urlpatterns = [
    path('chat/', views.index, name='index'),
    path('chats/', views.chats, name='chats'),
]
