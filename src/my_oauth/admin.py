from my_oauth.models import Form, Service, Token
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Service)
class ServiceAdmin(BaseModelAdmin):
    list_display = ['name', 'title', '_has_refresh_token', 'disable']
    search_fields = ['name', 'title']

    def _has_refresh_token(self, obj):
        return bool(obj.refresh_token_uri)
    _has_refresh_token.boolean = True
    _has_refresh_token.short_description = 'RToken'


@admin_register(Token)
class TokenAdmin(BaseModelAdmin):
    list_display = ['service', 'coder', 'user_id', 'email', 'modified']
    search_fields = ['coder__user__username', 'email', 'data']
    list_filter = ['service']


@admin_register(Form)
class FormAdmin(BaseModelAdmin):
    list_display = ['name', 'service']
    search_fields = ['name']
    list_filter = ['service']
