from pyclist.admin import BaseModelAdmin, admin_register
from django.contrib import admin
from tg.models import Chat, History


@admin_register(Chat)
class ChatAdmin(BaseModelAdmin):
    search_fields = ['coder__user__username', 'title', 'last_command']
    list_display = ['chat_id', 'coder', 'title', 'last_command']


@admin_register(History)
class HistoryAdmin(BaseModelAdmin):
    search_fields = ['chat__coder__user__username', 'message']
    list_display = ['chat', 'message', 'created']
