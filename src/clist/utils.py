#!/usr/bin/env python3

import logging
import re
from copy import deepcopy
from functools import cache
from importlib import import_module
from queue import SimpleQueue
from urllib.parse import urljoin

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django_super_deduper.merge import MergedModelInstance

from clist.templatetags.extras import canonize, get_problem_key, get_problem_name, get_problem_short


def update_accounts_by_coders(accounts, progress_bar=None) -> int:
    ret = 0
    accounts = accounts.prefetch_related('coders').select_related('resource')
    for account in accounts:
        ret += update_account_by_coders(account)
        if progress_bar is not None:
            progress_bar.update()
    return ret


def update_account_by_coders(account) -> bool:
    url = False
    custom_countries = None
    for coder in account.coders.all():
        if url:
            url = True
        else:
            url = reverse('coder:profile', args=[coder.username]) + f'?resource={account.resource_id}'

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
    return bool(update_fields)


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


@transaction.atomic
def update_problems(contest, problems=None, force=False):
    if problems is not None and not force:
        if canonize(problems) == canonize(contest.info.get('problems')):
            return

    contest.info['problems'] = problems
    contest.save(update_fields=['info'])

    if hasattr(contest, 'stage'):
        return

    contest.n_problems = len(list(contest.problems_list))
    contest.save(update_fields=['n_problems'])

    contests_set = {contest.pk}
    contests_queue = SimpleQueue()
    contests_queue.put(contest)

    new_problem_ids = set()
    old_problem_ids = set(contest.problem_set.values_list('id', flat=True))
    old_problem_ids |= set(contest.individual_problem_set.values_list('id', flat=True))
    added_problems = dict()

    def link_problem_to_contest(problem, contest):
        ret = not problem.contests.filter(pk=contest.pk).exists()
        if ret:
            create_contest_problem_discussion(contest, problem)
            problem.contests.add(contest)
        if problem.id in old_problem_ids:
            old_problem_ids.remove(problem.id)
        new_problem_ids.add(problem.id)
        return ret

    Problem = apps.get_model('clist.Problem')
    while not contests_queue.empty():
        current_contest = contests_queue.get()
        problem_sets = current_contest.division_problems
        for division, problem_set in problem_sets:
            prev = None
            for index, problem_info in enumerate(problem_set, start=1):
                key = get_problem_key(problem_info)
                short = get_problem_short(problem_info)
                name = get_problem_name(problem_info)

                if problem_info.get('ignore'):
                    continue
                if prev and not problem_info.get('_info_prefix'):
                    if prev.get('group') and prev.get('group') == problem_info.get('group'):
                        continue
                    if prev.get('subname') and prev.get('name') == name:
                        continue
                prev = deepcopy(problem_info)
                info = deepcopy(problem_info)

                problem_contest = contest if 'code' not in problem_info else None

                added_problem = added_problems.get(key)
                if current_contest != contest and not added_problem:
                    continue

                if problem_info.get('skip_in_stats'):
                    problem = Problem.objects.filter(
                        contest=problem_contest,
                        resource=contest.resource,
                        key=key,
                    ).first()
                    if problem:
                        link_problem_to_contest(problem, contest)
                    continue

                url = info.pop('url', None)
                if info.pop('_no_problem_url', False):
                    url = getattr(added_problem, 'url', None) or url
                else:
                    url = url or getattr(added_problem, 'url', None)

                skip_rating = bool(contest.info.get('skip_problem_rating'))

                kinds = getattr(added_problem, 'kinds', [])
                if contest.kind and contest.kind not in settings.PROBLEM_IGNORE_KINDS and contest.kind not in kinds:
                    kinds.append(contest.kind)

                divisions = getattr(added_problem, 'divisions', [])
                if division and division not in divisions:
                    divisions.append(division)

                defaults = {
                    'index': index if getattr(added_problem, 'index', index) == index else None,
                    'short': short if getattr(added_problem, 'short', short) == short else None,
                    'name': name,
                    'slug': info.pop('slug', getattr(added_problem, 'slug', None)),
                    'divisions': divisions,
                    'kinds': kinds,
                    'url': url,
                    'n_attempts': info.pop('n_teams', 0) + getattr(added_problem, 'n_attempts', 0),
                    'n_accepted': info.pop('n_accepted', 0) + getattr(added_problem, 'n_accepted', 0),
                    'n_partial': info.pop('n_partial', 0) + getattr(added_problem, 'n_partial', 0),
                    'n_hidden': info.pop('n_hidden', 0) + getattr(added_problem, 'n_hidden', 0),
                    'n_total': info.pop('n_total', 0) + getattr(added_problem, 'n_total', 0),
                    'time': max(contest.start_time, getattr(added_problem, 'time', contest.start_time)),
                    'start_time': min(contest.start_time, getattr(added_problem, 'start_time', contest.start_time)),
                    'end_time': max(contest.end_time, getattr(added_problem, 'end_time', contest.end_time)),
                    'skip_rating': skip_rating and getattr(added_problem, 'skip_rating', skip_rating),
                }
                for rate_field, value_field in (
                    ('attempt_rate', 'n_attempts'),
                    ('acceptance_rate', 'n_accepted'),
                    ('partial_rate', 'n_partial'),
                    ('hidden_rate', 'n_hidden'),
                ):
                    defaults[rate_field] = defaults[value_field] / defaults['n_total'] if defaults['n_total'] else None

                if translation := info.pop('translation', None):
                    translation = {
                        f'{field}_{language}': value
                        for language, data in translation.items() for field, value in data.items()
                    }
                    defaults.update(translation)

                for optional_field in 'n_accepted_submissions', 'n_total_submissions':
                    if optional_field not in info:
                        continue
                    added_value = getattr(added_problem, optional_field, 0) or 0
                    defaults[optional_field] = info.pop(optional_field) + added_value
                if getattr(added_problem, 'rating', None) is not None:
                    problem_info['rating'] = added_problem.rating
                    info.pop('rating', None)
                elif 'rating' in info:
                    defaults['rating'] = info.pop('rating')
                if 'visible' in info:
                    defaults['visible'] = info.pop('visible')

                if 'archive_url' in info:
                    archive_url = info.pop('archive_url')
                elif contest.resource.problem_url and problem_contest is None:
                    archive_url = contest.resource.problem_url.format(key=key, **defaults)
                else:
                    archive_url = getattr(added_problem, 'archive_url', None)
                defaults['archive_url'] = archive_url

                if '_more_fields' in info:
                    info.update(info.pop('_more_fields'))
                info_prefix = info.pop('_info_prefix', None)
                info_prefix_fields = info.pop('_info_prefix_fields', None)
                if info_prefix:
                    for field in info_prefix_fields:
                        if field in info:
                            info[f'{info_prefix}{field}'] = info.pop(field)

                for field in 'short', 'code', 'name', 'tags', 'subname', 'subname_class':
                    info.pop(field, None)
                if added_problem:
                    added_info = deepcopy(added_problem.info or {})
                    added_info.update(info)
                    info = added_info
                defaults['info'] = info

                problem, created = Problem.objects.update_or_create(
                    contest=problem_contest,
                    resource=contest.resource,
                    key=key,
                    defaults=defaults,
                )

                link_problem_to_contest(problem, contest)

                problem.update_tags(problem_info.get('tags'), replace=not added_problem)

                added_problems[key] = problem

                for c in problem.contests.all():
                    if c.pk in contests_set:
                        continue
                    contests_set.add(c.pk)
                    contests_queue.put(c)
        current_contest.save(update_fields=['info'])

    while old_problem_ids:
        new_problems = Problem.objects.filter(id__in=new_problem_ids)
        old_problems = Problem.objects.filter(id__in=old_problem_ids)

        max_similarity_score = 0
        for old_problem in old_problems:
            for new_problem in new_problems:
                similarity_score = 0
                for weight, field in (
                    (1, 'index'),
                    (2, 'short'),
                    (3, 'slug'),
                    (5, 'name'),
                    (10, 'url'),
                    (15, 'archive_url'),
                ):
                    similarity_score += weight * (getattr(old_problem, field) == getattr(new_problem, field))
                if similarity_score > max_similarity_score:
                    max_similarity_score = similarity_score
                    opt_old_problem = old_problem
                    opt_new_problem = new_problem
        if max_similarity_score == 0:
            break
        old_problem_ids.remove(opt_old_problem.id)
        opt_old_problem.contest = opt_new_problem.contest

        # FIXME: 'GenericRelation' object has no attribute 'field'
        for activity in opt_old_problem.activities.all():
            try:
                activity.object_id = opt_new_problem.id
                activity.validate_unique()
            except ValidationError as e:
                logging.warning(f'ValidationError: {e}')
                activity.delete()

        MergedModelInstance.create(opt_new_problem, [opt_old_problem])
        opt_old_problem.delete()

    if old_problem_ids:
        for problem in Problem.objects.filter(id__in=old_problem_ids):
            problem.contests.remove(contest)
            if problem.contests.count() == 0:
                problem.delete()

    return True


def update_writers(contest, writers=None) -> bool | None:
    if writers is not None:
        if canonize(writers) == canonize(contest.info.get('writers')):
            return
        contest.info['writers'] = writers
        contest.save()

    writers = contest.info.get('writers', [])
    if not writers:
        contest.writers.clear()
        return

    resource = contest.resource
    contest_writers = set(contest.writers.values_list('key', flat=True))
    already_writers = set(writers) & contest_writers

    def get_account(writer):
        account = resource.account_set.filter(key=writer).first()
        if account:
            return account
        return resource.account_set.filter(key__iexact=writer).order_by('-n_contests').first()

    modified_writers = []
    for writer in writers:
        if writer in already_writers:
            modified_writers.append(writer)
            continue

        account = get_account(writer)
        if account is None and (renaming := resource.accountrenaming_set.filter(old_key__iexact=writer).first()):
            writer = renaming.new_key
            account = get_account(writer)
        if account is None:
            account, created = resource.account_set.get_or_create(key=writer)
        account.writer_set.add(contest)
        modified_writers.append(account.key)

    if delete_writers := contest_writers - set(modified_writers):
        for account in contest.writers.filter(key__in=delete_writers):
            contest.writers.remove(account)

    if modified_writers == writers:
        return False
    contest.info['writers'] = modified_writers
    contest.save(update_fields=['info'])
    return True
