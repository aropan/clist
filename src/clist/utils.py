#!/usr/bin/env python3

import logging
import re
from functools import cache
from importlib import import_module
from urllib.parse import urljoin

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
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
    regex = get_similar_contests_regex()
    title_regex = re.sub(regex, similar_contests_replacing, f'^{contest.title}$')
    contests_filter = Q(title__iregex=title_regex)
    if not re.match('^[^a-zA-Z]*$', contest.key):
        key_regex = re.sub(regex, similar_contests_replacing, f'^{contest.key}$')
        contests_filter |= Q(key__iregex=key_regex)
    contests_filter &= Q(resource_id=contest.resource_id, stage__isnull=True)
    return contest._meta.model.objects.filter(contests_filter)


class CreateContestProblemDiscussionError(Exception):
    pass


def create_contest_problem_discussions(contest):
    for problem in contest.problem_set.all():
        create_contest_problem_discussion(contest, problem)


def create_contest_problem_discussion(contest, problem):
    Discussion = apps.get_model('clist.Discussion')
    contest_discussions = Discussion.objects.filter(
        contest=contest,
        what_contest=contest,
        with_problem_discussions=True,
        where_telegram_chat__isnull=False,
    )
    TelegramBot = import_module('tg.bot').Bot()
    for discussion in contest_discussions:
        telegram_chat = discussion.where
        if Discussion.objects.filter(what_problem=problem, where_telegram_chat=telegram_chat).exists():
            continue
        with transaction.atomic():
            topic = None
            try:
                discussion.id = None
                discussion.problem = problem
                discussion.what = problem
                discussion.save()
                topic = TelegramBot.create_topic(telegram_chat.chat_id, problem.full_name)
                discussion.url = urljoin(discussion.url, str(topic.message_thread_id))
                discussion.info = {'topic': topic.to_dict()}
                discussion.save()
            except Exception as e:
                if topic is not None:
                    TelegramBot.delete_topic(telegram_chat.chat_id, topic.message_thread_id)
                raise CreateContestProblemDiscussionError(e)
