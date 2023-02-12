from favorites.models import Activity

from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Activity)
class ActivityAdmin(BaseModelAdmin):
    list_display = ['coder', 'activity_type', 'content_type', 'content_object']
    list_filter = ['activity_type']
    search_fields = ['coder__username']
