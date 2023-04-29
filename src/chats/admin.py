from chats.models import Chat, ChatLog, ExternalChat
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Chat)
class ChatAdmin(BaseModelAdmin):
    list_display = ['name', 'slug', 'chat_type', 'modified']
    list_filter = ['chat_type']
    search_fields = ['name', 'slug']


@admin_register(ChatLog)
class ChatLogAdmin(BaseModelAdmin):
    list_display = ['chat', 'coder', 'action', 'context', 'modified']
    list_filter = ['chat__chat_type']
    search_fields = ['chat__name']


@admin_register(ExternalChat)
class ExternalChatAdmin(BaseModelAdmin):
    list_display = ['related', 'chat_type', 'chat_id', 'modified']
    one_line_fields = ['chat_id']
    list_filter = ['chat_type']
