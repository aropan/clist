#!/usr/bin/env python3

from functools import partial

from django.contrib import messages


class RequestLogger:

    def __init__(self, request):
        self.request_ = request

    def __getattr__(self, attr):
        ret = getattr(messages, attr)
        if callable(ret):
            ret = partial(ret, self.request_)
        return ret


def get_filtered_list(request, field, options=None):
    values = [
        value
        for value in request.GET.getlist(field)
        if options is not None and value in options or options is None and value
    ]
    if values and isinstance(options, list):
        for value in values[::-1]:
            options.remove(value)
            options.insert(0, value)
    return values


def get_filtered_value(request, field, options=None, default_first=None, allow_empty=False):
    if allow_empty and '' not in options:
        options = options + ['']
    ret = get_filtered_list(request, field, options)
    if ret:
        return ret[-1]
    if default_first and options:
        return options[0]
    return None


def custom_request(request):
    setattr(request, 'logger', RequestLogger(request))
    setattr(request, 'get_filtered_list', partial(get_filtered_list, request))
    setattr(request, 'get_filtered_value', partial(get_filtered_value, request))
    return request
