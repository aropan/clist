from django.contrib import admin
from django.contrib.auth.models import Permission
from easy_select2 import select2_modelform


def admin_register(*args, **kwargs):
    def _model_admin_wrapper(admin_class):
        admin_class = admin.register(*args, **kwargs)(admin_class)
        setattr(admin_class, 'form', select2_modelform(next(iter(args))))
        return admin_class
    return _model_admin_wrapper


class BaseModelAdmin(admin.ModelAdmin):
    readonly_fields = ['created', 'modified']
    save_as = True
    ordering = ['-modified']

    class Meta:
        abstract = True


@admin_register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'content_type', 'codename']
    search_fields = ['name']
