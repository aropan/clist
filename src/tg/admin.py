from pyclist.admin import BaseModelAdmin, admin_register
from tg.models import Chat, History


@admin_register(Chat)
class ChatAdmin(BaseModelAdmin):
    search_fields = ['coder__user__username', 'title', 'last_command']
    list_display = ['chat_id', 'thread_id', 'coder', 'is_group', 'title', 'name', 'last_command', 'settings']
    list_filter = ['is_group']


@admin_register(History)
class HistoryAdmin(BaseModelAdmin):
    search_fields = ['chat__coder__user__username', 'message']
    list_display = ['chat', 'message', 'created']
