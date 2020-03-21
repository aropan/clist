from django import forms
from django.contrib import admin
from django.contrib.auth.models import Permission
from easy_select2 import select2_modelform
from django.db import connection, transaction, models
from django.core.cache import cache
from django.core.paginator import Paginator
from django.contrib.postgres import fields
from django_json_widget.widgets import JSONEditorWidget


class CachingPaginator(Paginator):
    '''
    A custom paginator that helps to cut down on the number of
    SELECT COUNT(*) form table_name queries. These are really slow, therefore
    once we execute the query, we will cache the result which means the page
    numbers are not going to be very accurate but we don't care
    '''

    def _get_count(self):
        """
        Returns the total number of objects, across all pages.
        """
        if getattr(self, '_count', None) is None:
            try:
                key = "adm:{0}:count".format(hash(self.object_list.query.__str__()))
                self._count = cache.get(key, -1)
                if self._count == -1:
                    with transaction.atomic(), connection.cursor() as cursor:
                        if not self.object_list.query.where:
                            # This query that avoids a count(*) alltogether is
                            # stolen from https://djangosnippets.org/snippets/2593/
                            cursor.execute(
                                "SELECT reltuples FROM pg_class WHERE relname = %s",
                                [self.object_list.query.model._meta.db_table]
                            )
                            self._count = int(cursor.fetchone()[0])
                        else:
                            try:
                                cursor.execute('SET LOCAL statement_timeout TO 2000;')
                                self._count = self.object_list.count()
                            except Exception:
                                return 1
                    cache.set(key, self._count, 3600)
            except Exception:
                self._count = len(self.object_list)
        return self._count
    count = property(_get_count)


def admin_register(*args, **kwargs):
    def _model_admin_wrapper(admin_class):
        admin_class = admin.register(*args, **kwargs)(admin_class)
        setattr(admin_class, 'form', select2_modelform(next(iter(args))))
        return admin_class
    return _model_admin_wrapper


class BaseModelAdmin(admin.ModelAdmin):
    readonly_fields = ['created', 'modified']
    save_as = True
    paginator = CachingPaginator
    show_full_result_count = False

    formfield_overrides = {
        fields.JSONField: {'widget': JSONEditorWidget},
    }

    def formfield_for_dbfield(self, db_field, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, **kwargs)
        if isinstance(db_field, models.fields.CharField) and db_field.name in getattr(self, 'textarea_fields', []):
            formfield.widget = forms.Textarea(attrs=formfield.widget.attrs)
        return formfield

    class Meta:
        abstract = True


@admin_register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ['name', 'content_type', 'codename']
    search_fields = ['name']
