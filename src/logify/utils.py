#!/usr/bin/env python3

from contextlib import contextmanager

from logify.models import EventLog, EventStatus


@contextmanager
def failed_on_exception(event_log):
    try:
        yield
    except Exception as e:
        if event_log:
            event_log.update_error(str(e))
        raise e


@contextmanager
def logging_event(**kwargs):
    event_log = EventLog.objects.create(**kwargs)
    with failed_on_exception(event_log):
        yield event_log
    event_log.update_status(EventStatus.COMPLETED)
