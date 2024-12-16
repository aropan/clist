#!/usr/bin/env python3

from functools import partial
from typing import Optional

from django.contrib import messages

from clist.models import Resource


class RequestLogger:

    def __init__(self, request):
        self.request_ = request

    def __getattr__(self, attr):
        ret = getattr(messages, attr)
        if callable(ret):
            ret = partial(ret, self.request_)
        return ret


def get_resource(self, field='resource') -> Optional[Resource]:
    resource = self.GET.get(field)
    return Resource.get(resource)


def get_filtered_list(self, field, options=None, method='GET'):
    if method not in ['GET', 'POST']:
        raise ValueError(f'Invalid method: {method}')

    values = []
    values_set = set()
    for value in getattr(self, method).getlist(field):
        if value in values_set:
            continue
        if options is not None and value in options or options is None and value:
            values.append(value)
            values_set.add(value)

    if values and isinstance(options, list):
        for value in values[::-1]:
            options.remove(value)
            options.insert(0, value)
    return values


def get_filtered_value(self, field, options=None, default_first=None, allow_empty=False):
    if allow_empty and '' not in options:
        options = options + ['']
    ret = self.get_filtered_list(field, options)
    if ret:
        return ret[-1]
    if default_first and options:
        return options[0]
    return None


def set_canonical(self, url):
    url = self.build_absolute_uri(url)
    self.canonical_url = url
    return self


def has_contest_perm(self, perm, contest):
    if not self.user.is_authenticated:
        return False
    if self.user.is_superuser:
        return True
    return self.user.has_perm(perm, contest.resource) or self.user.has_perm(perm, contest)


def set_security_cookie(request, *args, **kwargs):
    kwargs.setdefault('secure', True)
    kwargs.setdefault('httponly', True)
    kwargs.setdefault('samesite', 'Strict')
    request.set_cookie(*args, **kwargs)


def CustomRequest(request):
    setattr(request, 'logger', RequestLogger(request))
    setattr(request, 'get_resource', partial(get_resource, request))
    setattr(request, 'get_filtered_list', partial(get_filtered_list, request))
    setattr(request, 'get_filtered_value', partial(get_filtered_value, request))
    setattr(request, 'canonical_url', None)
    setattr(request, 'set_canonical', partial(set_canonical, request))
    setattr(request, 'has_contest_perm', partial(has_contest_perm, request))
    setattr(request, 'set_security_cookie', partial(set_security_cookie, request))
    return request
