from pyclist.admin import BaseModelAdmin, admin_register
from django_markdown.admin import MarkdownModelAdmin
from django.contrib import admin
from blog.models import Entry


@admin_register(Entry)
class EntryAdmin(MarkdownModelAdmin, BaseModelAdmin):
    list_display = ('title', 'created', )
    prepopulated_fields = {'slug': ('title', )}
