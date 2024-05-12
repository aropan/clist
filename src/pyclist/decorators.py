#!/usr/bin/env python3

import contextlib
import logging
import re
from functools import wraps

import numpy as np
from django.conf import settings
from django.db import connection
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import redirect, render
from django.urls import resolve, reverse
from stringcolor import bold, cs

from clist.models import Contest
from clist.templatetags.extras import query_transform, slug, toint

logger = logging.getLogger(__name__)


def inject_contest():
    def decorator(view):
        @wraps(view)
        def decorated(request, title_slug=None, contest_id=None, contests_ids=None, *args, **kwargs):

            contests = Contest.objects.annotate_favorite(request.user)
            to_redirect = False
            contest = None
            if contest_id is not None:
                contest = contests.filter(pk=contest_id).first()
                if title_slug is None:
                    to_redirect = True
                else:
                    if contest is None or slug(contest.title) != title_slug:
                        contest = None
                        title_slug += f'-{contest_id}'
            if contest is None and title_slug is not None:
                contests_iterator = contests.filter(slug=title_slug).iterator()

                contest = None
                try:
                    contest = next(contests_iterator)
                    another = next(contests_iterator)
                except StopIteration:
                    another = None
                if contest is None:
                    return HttpResponseNotFound()
                if another is None:
                    to_redirect = True
                else:
                    return redirect(reverse('ranking:standings_list') + f'?search=slug:{title_slug}')

            if contests_ids is not None:
                cids, contests_ids = list(map(toint, contests_ids.split(','))), []
                for cid in cids:
                    if cid not in contests_ids:
                        contests_ids.append(cid)
                contest = contests.filter(pk=contests_ids[0]).first()
                kwargs['other_contests'] = list(contests.filter(pk__in=contests_ids[1:]))
            if contest is None:
                return HttpResponseNotFound()

            if to_redirect:
                resolved = resolve(request.path)
                viewname = resolved.app_name + ':' + resolved.url_name.split('_')[0]
                query = query_transform(request)
                url = reverse(viewname, kwargs={'title_slug': slug(contest.title),
                                                'contest_id': str(contest.pk)})
                if query:
                    query = '?' + query
                return redirect(url + query)

            response = view(request, *args, contest=contest, **kwargs)
            return response

        return decorated

    return decorator


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
        query_sql = re.sub(r'%d\b(, %d\b)+', '%ds', query_sql)  # replace many numbers
        query_sql = re.sub(r'%s\b(, %s\b)+', '%ss', query_sql)  # replace many strings
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


def extra_context_without_pagination(perm):
    def decorator(view):
        @wraps(view)
        def decorated(request, *args, **kwargs):
            if (
                request.user.is_authenticated
                and 'full_table' in request.GET
                and request.user.has_perm(perm)
            ):
                extra_context = kwargs.setdefault('extra_context', {})
                extra_context.update({'without_pagination': True})
            return view(request, *args, **kwargs)

        return decorated

    return decorator
