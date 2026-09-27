from crispy_forms.bootstrap import AppendedText, FormActions
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Hidden, Layout, Submit
from django.forms import ChoiceField, ModelForm

from notification.models import Notification


class NotificationForm(ModelForm):
    class Meta:
        model = Notification
        fields = (
            "method",
            "enable",
            "before",
            "period",
            "with_updates",
            "with_results",
            "with_virtual",
            "clear_on_delete",
        )
        # Django Meta consumes this value directly; an annotation adds an invalid Meta attribute.
        help_texts = {  # ruff: ignore[mutable-class-default]
            "method": ('You can <a href="/settings/filters/">configure filters</a> for each method'),
            "before": ("How much before event to send notifications"),
            "period": ("Frequency of notifications"),
            "with_updates": ("Notify about updates"),
            "with_results": ("Notify about results"),
            "with_virtual": ("Notify about end of the virtual a day before"),
            "clear_on_delete": ("Delete message in a day (only for telegram, need delete message permission)"),
        }
        # Django Meta consumes this value directly; an annotation adds an invalid Meta attribute.
        labels = {  # ruff: ignore[mutable-class-default]
            "with_updates": "Updates",
            "with_results": "Results",
            "with_virtual": "Virtual",
            "clear_on_delete": "Clear",
        }

    def __init__(self, coder, *args, **kwargs):
        super().__init__(*args, **kwargs)
        methods = coder.get_notifications()
        self.fields["method"] = ChoiceField(choices=methods)

    helper = FormHelper()
    helper.form_method = "POST"
    helper.form_class = "form-horizontal"
    helper.label_class = "col-sm-1"
    helper.field_class = "col-sm-4"
    helper.layout = Layout(
        Field("method", css_class="input-sm"),
        AppendedText("before", "minute(s)", css_class="input-sm"),
        Field("period", css_class="input-sm"),
        Field("with_updates", template="crispy_forms/boolean_field.html"),
        Field("with_results", template="crispy_forms/boolean_field.html"),
        Field("with_virtual", template="crispy_forms/boolean_field.html"),
        Field("clear_on_delete", template="crispy_forms/boolean_field.html"),
        Hidden("action", "notification"),
        Hidden("pk", ""),
        FormActions(Submit("add", "Add", css_class="btn-primary")),
    )
