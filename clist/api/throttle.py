#!/usr/bin/env python3

import time

from django.core.cache import cache
from tastypie.throttle import CacheThrottle

from true_coders.models import Coder


class CustomCacheThrottle(CacheThrottle):

    def convert_identifier_to_key(self, identifier):
        return str(identifier)

    def should_be_throttled(self, identifier, **kwargs):
        key = self.convert_identifier_to_key(identifier)
        limit_key = key + '[limit]'

        now = int(time.time())
        timeframe = int(self.timeframe)
        throttle_at = int(cache.get(limit_key, self.throttle_at))

        minimum_time = now - timeframe
        times_accessed = [access for access in cache.get(key, []) if access >= minimum_time]
        cache.set(key, times_accessed, self.expiration)

        if len(times_accessed) >= throttle_at:
            return timeframe - (now - times_accessed[-throttle_at])

        if limit_key not in cache:
            settings = Coder.objects.filter(username=identifier).values_list('settings', flat=True)
            settings = settings[0] if settings else {}
            throttle_at = settings.get('api_throttle_at', self.throttle_at)
            cache.set(limit_key, throttle_at, 3600)

        return False
