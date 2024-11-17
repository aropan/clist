from django.urls import reverse
from django.utils.html import format_html

from logify.models import EventLog, PgStat
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(EventLog)
class EventLogAdmin(BaseModelAdmin):
    list_display = ['id', 'related_object_link', 'name', 'status', 'message', 'created', 'elapsed', 'environment']
    list_filter = ['environment', 'name', 'status', 'resource']
    search_fields = ['contest__title', 'contest__host', 'resource__host', 'name', 'message']
    search_entirely = True

    def related_object_link(self, obj):
        url = reverse(f'admin:{obj.content_type.app_label}_{obj.content_type.model}_change', args=[obj.object_id])
        return format_html('<a href="{}">{}</a>', url, obj.related)

    related_object_link.short_description = 'Related Object'


@admin_register(PgStat)
class PgStatAdmin(BaseModelAdmin):
    list_display = ['id', 'table_name', 'app_name', 'pretty_table_size', 'pretty_diff_size', 'table_len',
                    'tuple_percent', 'dead_tuple_percent', 'free_percent',
                    'last_vacuum', 'last_autovacuum', 'last_analyze', 'last_autoanalyze',
                    'created', 'modified']
    list_filter = ['app_name']
    search_fields = ['table_name']
    ordering = ['-table_size']

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]
