#!/usr/bin/env python3

from datetime import timedelta

from django.db import models
from pytimeparse.timeparse import timeparse


def parse_duration(value):
    seconds = int(value) if value.isdigit() else timeparse(value)
    return timedelta(seconds=seconds)


class Epoch(models.expressions.Func):
    template = 'EXTRACT(epoch FROM %(expressions)s)::INTEGER'
    output_field = models.IntegerField()
