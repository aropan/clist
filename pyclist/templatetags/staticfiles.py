import os

from django.conf import settings
from django import template

register = template.Library()


@register.simple_tag
def static_ts(path):
    url = os.path.join(settings.STATIC_URL, path)
    folders = [settings.STATIC_ROOT]
    if settings.DEBUG:
        folders.append(os.path.join(settings.BASE_DIR, 'static'))
    for folder in folders:
        filepath = os.path.join(folder, path)
        if not os.path.exists(filepath):
            continue
        timestamp = int(os.path.getmtime(filepath))
        url = f'{url}?{timestamp}'
        break
    return url
