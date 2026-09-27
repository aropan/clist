from typing import ClassVar

from favorites.models import Activity
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Activity)
class ActivityAdmin(BaseModelAdmin):
    list_display: ClassVar = ["coder", "activity_type", "content_type", "content_object"]
    list_filter: ClassVar = ["activity_type"]
    search_fields: ClassVar = ["coder__username"]
