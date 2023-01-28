#!/usr/bin/env python3

from datetime import timedelta

import dateutil.parser
from django.db import models
from django.utils.timezone import now
from pytimeparse.timeparse import timeparse


def parse_duration(value):
    seconds = int(value) if value.isdigit() else timeparse(value)
    return timedelta(seconds=seconds)


def parse_datetime(value, timezone=None):
    if value.endswith('ago'):
        return now() - parse_duration(value[:-3].strip())
    if timezone:
        value += ' ' + timezone
    return dateutil.parser.parse(value)


class Epoch(models.expressions.Func):
    template = 'EXTRACT(epoch FROM %(expressions)s)::INTEGER'
    output_field = models.IntegerField()
