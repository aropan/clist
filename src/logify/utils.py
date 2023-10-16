#!/usr/bin/env python3

from contextlib import contextmanager

from logify.models import EventStatus


@contextmanager
def failed_on_exception(event_log):
    try:
        yield
    except Exception as e:
        if event_log:
            event_log.update_status(EventStatus.EXCEPTION, message=str(e))
        raise e
