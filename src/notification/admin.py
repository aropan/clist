from sql_util.utils import SubqueryCount

from notification.models import Calendar, Notification, NotificationMessage, Subscription, Task
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Notification)
class NotificationAdmin(BaseModelAdmin):
    list_display = ['coder', 'method', 'before', 'period', 'last_time', 'modified']
    list_filter = ['method']
    search_fields = ['coder__user__username', 'method', 'period']


@admin_register(Subscription)
class SubscriptionAdmin(BaseModelAdmin):
    list_display = ['coder', 'method', 'enable', 'n_accounts', 'n_coders',
                    'top_n', '_with_first_accepted',
                    'resource', 'contest', 'coder_list', 'coder_chat']
    list_filter = ['enable', 'method']
    search_fields = ['coder__username', 'accounts__key', 'coders__username']

    def n_accounts(self, obj):
        return obj.n_accounts

    def n_coders(self, obj):
        return obj.n_coders

    def _with_first_accepted(self, obj):
        return bool(obj.with_first_accepted)
    _with_first_accepted.boolean = True
    _with_first_accepted.short_description = 'AC'

    def get_queryset(self, request):
        ret = super().get_queryset(request)
        ret = ret.annotate(n_accounts=SubqueryCount('accounts'))
        ret = ret.annotate(n_coders=SubqueryCount('coders'))
        return ret

    def get_readonly_fields(self, *args, **kwargs):
        return ['last_contest', 'last_update'] + super().get_readonly_fields(*args, **kwargs)


@admin_register(Task)
class TaskAdmin(BaseModelAdmin):
    list_display = ['notification', 'created', 'modified', 'is_sent']
    list_filter = ['is_sent']
    search_fields = ['subject', 'message', 'periodical_notification__coder__username', 'subscription__coder__username']


@admin_register(Calendar)
class CalendarAdmin(BaseModelAdmin):
    list_display = ['name', 'coder', 'category', 'resources', 'descriptions', 'created', 'modified']
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
