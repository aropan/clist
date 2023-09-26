import humanize

from logify.models import EventLog

from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(EventLog)
class EventLogAdmin(BaseModelAdmin):
    list_display = ['related', 'name', 'status', 'message', 'created', '_elapsed_time']
    list_filter = ['name', 'status', 'resource']
    search_fields = ['contest__title', 'name', 'message']

    def _elapsed_time(self, obj):
        return humanize.naturaldelta(obj.modified - obj.created)
    _elapsed_time.short_description = 'Elapsed'
