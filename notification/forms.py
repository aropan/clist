from django.forms import ModelForm, ChoiceField
from notification.models import Notification

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Submit, Layout, Hidden
from crispy_forms.bootstrap import FormActions, AppendedText


class NotificationForm(ModelForm):

    class Meta:
        model = Notification
        exclude = ['coder']
        help_texts = {
            'method': ('You can <a href="/settings#filtres-tab">configure filters</a> for each method'),
            'before': ('How much before event to send notifications'),
            'period': ('Frequency of notifications'),
        }

    def __init__(self, coder, *args, **kwargs):
        super(NotificationForm, self).__init__(*args, **kwargs)

        methods = list(Notification.METHODS_CHOICES)
        for chat in coder.chat_set.filter(is_group=True):
            name = chat.get_group_name()
            methods.append(('telegram:{}'.format(name), name))
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
        Hidden('action', 'notification'),
        FormActions(Submit('add', 'Add', css_class='btn-primary'))
    )
