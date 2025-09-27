from import_export import fields, resources, widgets
from import_export.admin import ImportExportModelAdmin

from my_oauth.models import Credential, Form, Service, Token
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
    list_display = ['id', 'name', 'service', 'modified']
    search_fields = ['name']
    list_filter = ['service']
    ordering = ['-modified']

    def get_readonly_fields(self, *args, **kwargs):
        return ['id'] + list(super().get_readonly_fields(*args, **kwargs))


class CredentialResource(resources.ModelResource):
    form_id = fields.Field(column_name='form', attribute='form_id', widget=widgets.CharWidget())

    class Meta:
        model = Credential
        fields = ('form_id', 'login', 'password')
        import_id_fields = ('form_id', 'login')
        use_bulk = True
        batch_size = 100
        skip_unchanged = True


@admin_register(Credential)
class CredentialAdmin(ImportExportModelAdmin, BaseModelAdmin):
    list_display = ('login', 'token', 'state', 'modified')
    list_filter = ('state', 'form')
    search_fields = ('login', 'token__coder__user__username', 'token__email', 'token__user_id')
    raw_id_fields = ('form', 'token')
    resource_classes = [CredentialResource]
    skip_import_confirm = True