from notification.models import Calendar, Notification, NotificationMessage, Task
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Notification)
class NotificationAdmin(BaseModelAdmin):
    list_display = ['coder', 'method', 'before', 'period', 'last_time', 'modified']
    list_filter = ['method']
    search_fields = ['coder__user__username', 'method', 'period']

    def get_readonly_fields(self, request, obj=None):
        return super().get_readonly_fields(request, obj)


@admin_register(Task)
class TaskAdmin(BaseModelAdmin):
    list_display = ['notification', 'created', 'modified', 'is_sent']
    list_filter = ['notification__method', 'is_sent']
    search_fields = ['notification__coder__user__username', 'notification__method', 'subject', 'message']


@admin_register(Calendar)
class CalendarAdmin(BaseModelAdmin):
    list_display = ['name', 'coder', 'category', 'resources', 'uuid', 'created', 'modified']
    search_fields = ['name', 'coder__username', 'category']


@admin_register(NotificationMessage)
class NotificationMessageAdmin(BaseModelAdmin):
    list_display = ['to', 'level', 'is_read', 'read_at', 'sender', 'created']
    list_filter = ['is_read']
    search_fields = ['text', 'to__username', 'sender__username']

    def unread(self, request, queryset):
        self.message_user(request, queryset.update(is_read=False))
    unread.short_description = 'Unread'

    actions = [unread]
