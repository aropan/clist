from pyclist.admin import BaseModelAdmin, admin_register
from django.contrib import admin
from my_oauth.models import Service, Token


@admin_register(Service)
class ServiceAdmin(BaseModelAdmin):
    list_display = ['name', 'title']
    search_fields = ['name', 'title']


@admin_register(Token)
class TokenAdmin(BaseModelAdmin):
    list_display = ['service', 'coder', 'user_id', 'email', 'modified']
    search_fields = ['coder__user__username', 'email']
