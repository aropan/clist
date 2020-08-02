#!/usr/bin/env python3

from functools import wraps

from django.shortcuts import render


def context_pagination():
    def decorator(view):
        @wraps(view)
        def decorated(request, *args, extra_context=None, **kwargs):
            template, context = view(request, *args, **kwargs)
            if extra_context is not None:
                context.update(extra_context)
            return render(request, template, context)

        return decorated

    return decorator
