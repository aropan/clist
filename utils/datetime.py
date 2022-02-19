#!/usr/bin/env python3

from datetime import timedelta

from pytimeparse.timeparse import timeparse


def parse_duration(value):
    seconds = int(value) if value.isdigit() else timeparse(value)
    return timedelta(seconds=seconds)
