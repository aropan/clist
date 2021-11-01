from crispy_forms.bootstrap import AppendedText, FormActions
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Hidden, Layout, Submit
from django.forms import ChoiceField, ModelForm

from notification.models import Notification


class NotificationForm(ModelForm):

    class Meta:
        model = Notification
        exclude = ['coder', 'last_time', 'secret']
        help_texts = {
            'method': ('You can <a href="/settings#filtres-tab">configure filters</a> for each method'),
            'before': ('How much before event to send notifications'),
            'period': ('Frequency of notifications'),
            'with_updates': ('Notify about updates'),
            'with_results': ('Notify about results'),
        }
        labels = {
            'with_updates': 'Updates',
            'with_results': 'Results',
        }

    def __init__(self, coder, *args, **kwargs):
        super(NotificationForm, self).__init__(*args, **kwargs)

        methods = coder.get_notifications()
        self.fields['method'] = ChoiceField(choices=methods)

    helper = FormHelper()
    helper.form_method = 'POST'
    helper.form_class = 'form-horizontal'
    helper.label_class = 'col-sm-1'
    helper.field_class = 'col-sm-4'
    helper.layout = Layout(
        Field('method', css_class='input-sm'),
        AppendedText('before', 'minute(s)', css_class='input-sm'),
        Field('period', css_class='input-sm'),
        Field('with_updates', template='crispy_forms/boolean_field.html'),
        Field('with_results', template='crispy_forms/boolean_field.html'),
        Hidden('action', 'notification'),
        Hidden('pk', ''),
        FormActions(Submit('add', 'Add', css_class='btn-primary'))
    )
