from django.urls import path

from notification import views

app_name = 'notification'

urlpatterns = [
    path('calendar/<uuid:uuid>/', views.EventFeed(), name='calendar'),
    path('messages/', views.messages, name='messages'),
]
