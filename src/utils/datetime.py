#!/usr/bin/env python3

from datetime import datetime, timedelta

import dateutil.parser
import pytz
from django.conf import settings
from django.db import models
from django.utils.timezone import now, utc
from pytimeparse.timeparse import timeparse

from clist.templatetags.extras import get_timezones


def parse_duration(value):
    seconds = int(value) if value.isdigit() else timeparse(value)
    return timedelta(seconds=seconds)


def parse_datetime(value, timezone=None):
    if value.endswith('ago'):
        return now() - parse_duration(value[:-3].strip())
    if timezone:
        value += ' ' + timezone
    return dateutil.parser.parse(value)


def datetime_from_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp, tz=utc)


def datetime_to_str(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S %z')


class Epoch(models.expressions.Func):
    template = 'EXTRACT(epoch FROM %(expressions)s)::INTEGER'
    output_field = models.IntegerField()


def get_timezone(request):
    tz = request.GET.get("timezone", None)
    if tz:
        result = None
        try:
            pytz.timezone(tz)
            result = tz
        except Exception:
            if tz.startswith(" "):
                tz = tz.replace(" ", "+")
            for tzdata in get_timezones():
                if str(tzdata["offset"]) == tz or tzdata["repr"] == tz:
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
