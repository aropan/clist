#!/usr/bin/env python3

from datetime import datetime, timedelta, timezone
from functools import wraps

import arrow
import dateutil.parser
import pytz
from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils.timezone import now
from pytimeparse.timeparse import timeparse

from clist.templatetags.extras import get_timezones


def parse_duration(value):
    seconds = int(value) if str(value).isdigit() else timeparse(value)
    return timedelta(seconds=seconds)


def parse_datetime(value, tz=None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return arrow.get(value).datetime
    if value.endswith('ago'):
        return now() - parse_duration(value[:-3].strip())
    if tz:
        value = f'{value} {tz}'
    return dateutil.parser.parse(value).astimezone(tz=timezone.utc)


def datetime_from_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def datetime_to_str(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S %z')


class Epoch(models.expressions.Func):
    template = 'EXTRACT(epoch FROM %(expressions)s)::INTEGER'
    output_field = models.IntegerField()


def get_timeformat(request):
    if "time_format" in request.GET:
        return request.GET["time_format"]
    ret = settings.TIME_FORMAT_
    if request.user.is_authenticated and hasattr(request.user, "coder"):
        ret = request.user.coder.settings.get("time_format", ret)
    return ret


def get_timezone(request):
    tz = request.GET.get("timezone")
    if tz:
        result = None
        try:
            pytz.timezone(tz)
            result = tz
        except Exception:
            if tz.startswith(" "):
                tz = tz.replace(" ", "+", 1)
            tzname = request.GET.get("tzname")
            for tzdata in get_timezones():
                if str(tzdata["offset"]) == tz or tzdata["repr"] == tz:
                    if result is None:
                        result = tzdata["name"]
                    if tzname is None:
                        break
                    if tzdata["name"] == tzname:
                        result = tzdata["name"]
                        break
        if result:
            if "update" in request.GET:
                if request.user.is_authenticated:
                    request.user.coder.timezone = result
                    request.user.coder.save()
                else:
                    request.session["timezone"] = result
                return
            return result

    if request.user.is_authenticated and hasattr(request.user, "coder"):
        return request.user.coder.timezone
    return request.session.get("timezone", settings.DEFAULT_TIME_ZONE_)


def timed_cache(timeout_cache):
    timeout_cache = parse_duration(timeout_cache).total_seconds()

    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            key = f'{func.__module__}.{func.__qualname__}.{args}.{kwargs}'
            key = key.replace(' ', '')
            ret = cache.get(key)
            if ret is None:
                ret = func(*args, **kwargs)
                cache.set(key, ret, timeout_cache)
            return ret

        return decorated

    return decorator
