from notification.models import Calendar, Notification, Task
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
