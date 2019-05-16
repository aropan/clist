import os

from django.conf import settings
from django import template

register = template.Library()


@register.simple_tag
def static_ts(path):
    url = os.path.join(settings.STATIC_URL, path)
    if not settings.DEBUG:
        filepath = os.path.join(settings.STATIC_ROOT, path)
        timestamp = int(os.path.getmtime(filepath))
        url = f'{url}?{timestamp}'
    return url
