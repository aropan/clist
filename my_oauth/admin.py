from pyclist.admin import BaseModelAdmin, admin_register
from my_oauth.models import Service, Token


@admin_register(Service)
class ServiceAdmin(BaseModelAdmin):
    list_display = ['name', 'title', 'disable']
    search_fields = ['name', 'title']


@admin_register(Token)
class TokenAdmin(BaseModelAdmin):
    list_display = ['service', 'coder', 'user_id', 'email', 'modified']
    search_fields = ['coder__user__username', 'email']
    list_filter = ['service']
