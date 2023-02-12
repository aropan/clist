from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def activity_action(activity_type, instance):
    '''
    This tag is used to display the activity state for a particular object to take action on it.
    '''

    content_type = instance._meta.model_name
    object_id = instance.pk
    enable = getattr(instance, 'is_favorite', False)

    icon_class = 'selected-activity fas' if enable else 'far'
    ret = (
        f'<i onclick="click_activity(event, this)"'
        f' class="activity fa-star fav {icon_class}"'
        f' data-activity-type="{activity_type}"'
        f' data-content-type="{content_type}"'
        f' data-object-id="{object_id}"'
        '></i>'
    )
    return mark_safe(ret)
