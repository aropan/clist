from typing import ClassVar

from chats.models import Chat, ChatLog, ExternalChat
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Chat)
class ChatAdmin(BaseModelAdmin):
    list_display: ClassVar = ["name", "slug", "chat_type", "modified"]
    list_filter: ClassVar = ["chat_type"]
    search_fields: ClassVar = ["name", "slug"]


@admin_register(ChatLog)
class ChatLogAdmin(BaseModelAdmin):
    list_display: ClassVar = ["chat", "coder", "action", "context", "modified"]
    list_filter: ClassVar = ["chat__chat_type"]
    search_fields: ClassVar = ["chat__name"]


@admin_register(ExternalChat)
class ExternalChatAdmin(BaseModelAdmin):
    list_display: ClassVar = ["related", "chat_type", "chat_id", "modified"]
    one_line_fields: ClassVar = ["chat_id"]
    list_filter: ClassVar = ["chat_type"]
