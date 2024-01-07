from clist.templatetags.extras import trim_to
from notes.models import Note
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Note)
class NoteAdmin(BaseModelAdmin):
    list_display = ['coder', 'content_type', 'content_object', 'trimmed_text', 'modified']
    search_fields = ['coder__username']

    def trimmed_text(self, obj):
        return trim_to(obj.text, 100)
