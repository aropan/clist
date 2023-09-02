from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def activity_action(activity_type, instance, callback=None, onclick='click_activity', name='activity'):
    '''
    This tag is used to display the activity state for a particular object to take action on it.
    '''

    content_type = instance._meta.model_name
    object_id = instance.pk

    activity_data = settings.FONTAWESOME_ICONS_[activity_type]
    icon_name = activity_data['name']
    selected_class = activity_data.get('selected_class', 'fas')
    unselected_class = activity_data.get('unselected_class', 'fas')
    if not hasattr(instance, activity_data['check_field']):
        return ''
    enable = getattr(instance, activity_data['check_field'])
    activity_class = f'selected-{name} {selected_class}' if enable else unselected_class

    ret = (
        f'<i onclick="{onclick}(event, this{f", {callback}" if callback else ""})"'
        f' class="{name} {icon_name} {activity_type} {activity_class}"'
        f' data-{name}-type="{activity_type}"'
        f' data-content-type="{content_type}"'
        f' data-object-id="{object_id}"'
        f' data-selected-class="{selected_class}"'
        f' data-unselected-class="{unselected_class}"'
        '></i>'
    )
    return mark_safe(ret)


@register.simple_tag
def activity_icon(activity_type, enable, name='activity'):
    activity_data = settings.FONTAWESOME_ICONS_[activity_type]
    icon_name = activity_data['name']
    selected_class = activity_data.get('selected_class', 'fas')
    unselected_class = activity_data.get('unselected_class', 'fas')
    activity_class = f'selected-{name} {selected_class}' if enable else unselected_class
    ret = f'<i class="{name} {icon_name} {activity_type} {activity_class}"></i>'
    return mark_safe(ret)


@register.simple_tag
def note_action(activity_type, instance, callback=None):
    return activity_action(activity_type, instance, callback=callback, onclick='click_note', name='note')
