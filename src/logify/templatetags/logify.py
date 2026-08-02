from django import template
from django.core.cache import cache

from logify.access import can_view_any_live_updates

register = template.Library()
LIVE_UPDATES_NAV_CACHE_TIMEOUT = 60


@register.filter
def can_view_live_updates(user):
    if not user or not user.is_authenticated:
        return False

    cache_key = f"live-updates-nav-permission:{user.pk}"
    can_view = cache.get(cache_key)
    if can_view is None:
        can_view = can_view_any_live_updates(user)
        cache.set(cache_key, can_view, timeout=LIVE_UPDATES_NAV_CACHE_TIMEOUT)
    return can_view
