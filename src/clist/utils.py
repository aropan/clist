#!/usr/bin/env python3

import re
from functools import cache

from django.db.models import Q
from django.urls import reverse


def update_accounts_by_coders(accounts):
    accounts = accounts.prefetch_related('coders').select_related('resource')
    for account in accounts:
        update_account_by_coders(account)


def update_account_by_coders(account):
    url = False
    custom_countries = None
    for coder in account.coders.all():
        if url:
            url = True
        else:
            url = reverse('coder:profile', args=[coder.username]) + f'?search=resource:{account.resource.host}'

        coder_custom_countries = coder.settings.get('custom_countries', {})
        if custom_countries is None:
            custom_countries = coder_custom_countries
        else:
            custom_countries = dict(
                set(custom_countries.items()) &
                set(coder_custom_countries.items())
            )
            if not custom_countries:
                break

    if isinstance(url, bool):
        url = account.account_default_url()

    update_fields = []

    if url != account.url:
        account.url = url
        update_fields.append('url')

    custom_countries = custom_countries or {}
    if custom_countries != account.info.get('custom_countries_', {}):
        account.info['custom_countries_'] = custom_countries
        update_fields.append('info')

    if update_fields:
        account.save(update_fields=update_fields)


@cache
def get_similar_contests_patterns():
    return {
        'number_with_ending': r'\b[0-9]+(?:th|st|nd|rd)\b',
        'number': r'\b[0-9]+\b',
        'roman_number': r'\b[IVXLCDM]+\b',
        'final': r'\.\s+[^.]*(?<=\s)\b[Ff]inals?\b[^.]*$',
        'subtitle': r'\.\s+[^.]*$',
    }


@cache
def get_similar_contests_regex():
    patterns = get_similar_contests_patterns()
    return '|'.join(rf'(?P<{group}>{regex})' for group, regex in patterns.items())


def similar_contests_replacing(match):
    patterns = get_similar_contests_patterns()
    for group, regex in patterns.items():
        if match.group(group):
            return regex.replace(r'\b', r'\y')


def similar_contests_queryset(contest):
    title = f'^{contest.title}$'
    regex = get_similar_contests_regex()
    title_regex = re.sub(regex, similar_contests_replacing, title)
    contests_filter = Q(title__iregex=title_regex, resource_id=contest.resource_id, stage__isnull=True)
    return contest._meta.model.objects.filter(contests_filter)
