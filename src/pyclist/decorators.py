#!/usr/bin/env python3

import re
from functools import wraps

import numpy as np
from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render


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


def analyze_db_queries(func):

    @wraps(func)
    def analyze_db_queries_wrapper(*args, **kwargs):
        initial_queries = len(connection.queries)
        result = func(*args, **kwargs)
        final_queries = connection.queries[initial_queries:]
        grouped_times = group_and_calculate_times(final_queries)
        log_grouped_times(grouped_times)
        return result

    return analyze_db_queries_wrapper


def group_and_calculate_times(queries):
    grouped = {}
    for query in queries:
        query_sql = query['sql']
        query_sql = re.sub(r'\b\d+\b', '%d', query_sql)  # replace number
        query_sql = re.sub(r'\'.+?\'', '%s', query_sql)  # replace string
        query_sql = re.sub(r'\bs\d+_x\d+\b', '%s', query_sql)  # replace savepoint
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
        print('{sum:.3f}ms ({avg:.3f}ms) {count} times: {query}'.format(**g))
