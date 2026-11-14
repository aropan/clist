import csv
from io import StringIO
from typing import ClassVar

import tablib
from django import forms
from import_export import fields, resources, widgets
from import_export.admin import ImportExportModelAdmin
from import_export.formats import base_formats
from import_export.forms import ImportForm

from my_oauth.models import Credential, Form, Service, Token
from pyclist.admin import BaseModelAdmin, admin_register


@admin_register(Service)
class ServiceAdmin(BaseModelAdmin):
    list_display: ClassVar = ["name", "title", "_has_refresh_token", "disable"]
    search_fields: ClassVar = ["name", "title"]

    def _has_refresh_token(self, obj):
        return bool(obj.refresh_token_uri)

    _has_refresh_token.boolean = True
    _has_refresh_token.short_description = "RToken"


@admin_register(Token)
class TokenAdmin(BaseModelAdmin):
    list_display: ClassVar = ["service", "coder", "user_id", "email", "modified"]
    search_fields: ClassVar = ["coder__user__username", "email", "data"]
    list_filter: ClassVar = ["service"]


@admin_register(Form)
class FormAdmin(BaseModelAdmin):
    list_display: ClassVar = ["id", "name", "service", "modified"]
    search_fields: ClassVar = ["name"]
    list_filter: ClassVar = ["service"]
    ordering: ClassVar = ["-modified"]

    def get_readonly_fields(self, *args, **kwargs):
        return ["id", *list(super().get_readonly_fields(*args, **kwargs))]


class CredentialTextFormat(base_formats.CSV):
    CONTENT_TYPE = "text/plain"

    def get_title(self):
        return "txt"

    def get_extension(self):
        return "txt"

    def create_dataset(self, in_stream, **kwargs):
        if isinstance(in_stream, bytes):
            in_stream = in_stream.decode(self.encoding or "utf-8-sig")
        dataset = tablib.Dataset(headers=["login", "password"])
        logins = set()
        reader = csv.reader(StringIO(in_stream), strict=True)
        for row in reader:
            if not row:
                continue
            if len(row) != 2 or not all(row):
                raise ValueError(f"Line {reader.line_num}: expected login,password with non-empty values.")
            if row[0] in logins:
                raise ValueError(f"Line {reader.line_num}: duplicate login.")
            logins.add(row[0])
            dataset.append(row)
        if not dataset:
            raise ValueError("No credentials to import.")
        return dataset

    def can_export(self):
        return False


class CredentialImportForm(ImportForm):
    form = forms.ModelChoiceField(
        queryset=Form.objects.order_by("name"),
        required=False,
        help_text=(
            "Applies to all rows; leave empty to use the form column in the file. "
            "TXT files: one login,password pair per line, without a header."
        ),
    )
    field_order: ClassVar = ["resource", "form", "import_file", "format"]

    def __init__(self, formats, resources, **kwargs):
        super().__init__(formats, resources, **kwargs)
        self.formats = formats

    def clean(self):
        cleaned_data = super().clean()
        format_index = cleaned_data.get("format")
        if format_index and self.formats[int(format_index)] is CredentialTextFormat and not cleaned_data.get("form"):
            self.add_error("form", "Select a form for TXT files.")
        return cleaned_data


class CredentialResource(resources.ModelResource):
    form_id = fields.Field(column_name="form", attribute="form_id", widget=widgets.CharWidget())

    def __init__(self, form_id=None, **kwargs):
        super().__init__(**kwargs)
        self.form_id = str(form_id) if form_id else None

    def before_import(self, dataset, **kwargs):
        super().before_import(dataset, **kwargs)
        if self.form_id:
            if "form" in (dataset.headers or []):
                del dataset["form"]
            dataset.append_col([self.form_id] * len(dataset), header="form")

    class Meta:
        model = Credential
        fields = ("form_id", "login", "password")
        import_id_fields = ("form_id", "login")
        use_bulk = True
        batch_size = 100
        skip_unchanged = True


@admin_register(Credential)
class CredentialAdmin(ImportExportModelAdmin, BaseModelAdmin):
    list_display = ("login", "token", "state", "modified")
    list_filter = ("state", "form")
    search_fields = ("login", "token__coder__user__username", "token__email", "token__user_id")
    raw_id_fields = ("form", "token")
    resource_classes: ClassVar = [CredentialResource]
    import_form_class = CredentialImportForm
    skip_import_confirm = True

    def get_import_formats(self):
        return [*super().get_import_formats(), CredentialTextFormat]

    def get_import_resource_kwargs(self, request, **kwargs):
        resource_kwargs = super().get_import_resource_kwargs(request, **kwargs)
        import_form = kwargs.get("form")
        if (
            import_form
            and hasattr(import_form, "cleaned_data")
            and (selected_form := import_form.cleaned_data.get("form"))
        ):
            resource_kwargs["form_id"] = selected_form.pk
        return resource_kwargs
