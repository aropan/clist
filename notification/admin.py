from pyclist.admin import BaseModelAdmin, admin_register
from notification.models import Notification, Task


@admin_register(Notification)
class NotificationAdmin(BaseModelAdmin):
    list_display = ['coder', 'method', 'before', 'period', 'last_time', 'modified']
    list_filter = ['method']
    search_fields = ['coder__user__username', 'method', 'period']

    def get_readonly_fields(self, request, obj=None):
        return ['last_time', ] + super().get_readonly_fields(request, obj)


@admin_register(Task)
class TaskAdmin(BaseModelAdmin):
    list_display = ['notification', 'created', 'modified', 'is_sent']
    list_filter = ['notification__method', 'is_sent']
    search_fields = ['notification__coder__user__username', 'notification__method', 'subject', 'message']
