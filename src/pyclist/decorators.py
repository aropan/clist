#!/usr/bin/env python3

import contextlib
import logging
import re
from functools import wraps

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render
from stringcolor import bold, cs

logger = logging.getLogger(__name__)


def context_pagination():
    def decorator(view):
        @wraps(view)
        def decorated(request, *args, extra_context=None, **kwargs):
            response = view(request, *args, **kwargs)
            if isinstance(response, HttpResponse):
                return response
            template, context = response
            if extra_context is not None:
                context.update(extra_context)
            return render(request, template, context)

        return decorated

    return decorator


@contextlib.contextmanager
def analyze_db_queries():
    initial_queries = len(connection.queries)
    yield
    final_queries = connection.queries[initial_queries:]
    grouped_times = group_and_calculate_times(final_queries)
    log_grouped_times(grouped_times)


def group_and_calculate_times(queries):
    grouped = {}
    for query in queries:
        query_sql = query['sql']
        query_sql = re.sub(r'\b\d+\b', '%d', query_sql)  # replace number
        query_sql = re.sub(r'\'.+?\'', '%s', query_sql)  # replace string
        query_sql = re.sub(r'\bs\d+_x\d+\b', '%s', query_sql)  # replace savepoint
        query_sql = re.sub(r'\b%d\b(, %d\b)+', '%ds', query_sql)  # replace many numbers
        query_sql = re.sub(r'\b%s\b(, %s\b)+', '%ss', query_sql)  # replace many strings
        grouped.setdefault(query_sql, []).append(query)
    total_times = []
    for key, queries in grouped.items():
        times = [float(q['time']) for q in queries]
        total_times.append({
            'query': key,
            'avg': np.mean(times),
            'sum': np.sum(times),
            'count': len(times),
        })
    return total_times


def log_grouped_times(grouped_times):
    grouped_times.sort(key=lambda x: x['sum'], reverse=True)
    mean = np.mean([g['sum'] for g in grouped_times])
    for g in grouped_times:
        if g['sum'] < mean:
            break
        msg = bold(f'{g["sum"]:.3f}') + ' ms'
        msg += ' (avg ' + bold(f'{g["avg"]:.3f}') + ' ms)'
        msg += ' ' + bold(f'{g["count"]}') + ' times'
        msg += ': ' + cs(g['query'], 'grey')
        print(msg)


def run_only_in_production(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not settings.DEBUG:
            return func(*args, **kwargs)
    return wrapper


def run_once(key):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not cache.get(key):
                result = func(*args, **kwargs)
                cache.set(key, True)
                return result
        return wrapper
    return decorator
