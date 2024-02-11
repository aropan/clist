#!/usr/bin/env python3

import functools
import json
import operator
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django_super_deduper.merge import MergedModelInstance
from tqdm import tqdm

from ranking.management.modules.common import LOG
from ranking.models import AccountRenaming, Statistics
from utils.logger import suppress_db_logging_context
from utils.math import max_with_none


@transaction.atomic
def rename_account(old_account, new_account):
    AccountRenaming.objects.update_or_create(
        resource=old_account.resource,
        old_key=old_account.key,
        defaults={'new_key': new_account.key},
    )
    AccountRenaming.objects.filter(
        resource=old_account.resource,
        old_key=new_account.key,
    ).delete()

    old_contests = old_account.statistics_set.values('contest')
    new_account.statistics_set.filter(contest__in=old_contests).delete()

    n_contests = new_account.n_contests + old_account.n_contests
    n_writers = new_account.n_writers + old_account.n_writers
    last_activity = max_with_none(old_account.last_activity, new_account.last_activity)
    last_submission = max_with_none(old_account.last_submission, new_account.last_submission)
    new_account = MergedModelInstance.create(new_account, [old_account])
    old_account.delete()
    new_account.n_contests = n_contests
    new_account.n_writers = n_writers
    new_account.last_activity = last_activity
    new_account.last_submission = last_submission
    new_account.save()
    return new_account


def clear_problems_fields(problems):
    if not problems:
        return
    for v in problems.values():
        if not isinstance(v, dict):
            continue
        v.pop('first_ac', None)
        v.pop('first_ac_of_all', None)


def to_canonize_str(data):
    return json.dumps(data, sort_keys=True)


def renaming_check(account, contest_keys, fields, contest_addition_update):
    if len(contest_keys) < 3:
        return
    key_counter = defaultdict(int)
    total_counter = 0
    max_counter_key = None
    for contest_key in tqdm(contest_keys, desc='renaming_check'):
        addition_update = contest_addition_update[contest_key]
        if '_rank' not in addition_update:
            continue
        total_counter += 1
        conditions = (Q(**{f'contest__{field}': contest_key}) for field in fields)
        condition = functools.reduce(operator.__or__, conditions)
        condition &= Q(place=addition_update['_rank'], contest__resource=account.resource)
        old_account_key = Statistics.objects.filter(condition).values_list('account__key', flat=True).first()
        if old_account_key:
            key_counter[old_account_key] += 1
            if max_counter_key is None or key_counter[max_counter_key] < key_counter[old_account_key]:
                max_counter_key = old_account_key
    if max_counter_key is None:
        return
    max_counter_val = key_counter.pop(max_counter_key)
    other_max_counter_val = max(key_counter.values(), default=0)
    if max_counter_val < max(other_max_counter_val * 2, 3):
        LOG.warning('Failed renaming %s, counter = %s', account, key_counter)
        return
    old_account = account.resource.account_set.get(key=max_counter_key)
    LOG.info('Renaming %s to %s', old_account, account)
    rename_account(old_account, account)
    return True


@suppress_db_logging_context()
def account_update_contest_additions(
    account,
    contest_addition_update,
    timedelta_limit=None,
    by=None,
    clear_rating_change=None,
    try_renaming_check=None,
):
    contest_keys = set(contest_addition_update.keys())

    fields = 'key' if by is None else by
    if isinstance(fields, str):
        fields = [fields]

    base_qs = Statistics.objects.filter(account=account)
    if timedelta_limit is not None and not clear_rating_change:
        base_qs.filter(modified__lte=timezone.now() - timedelta_limit)

    grouped_contest_keys = defaultdict(list)
    for contest_key, update in contest_addition_update.items():
        group = update.get('_group')
        if group:
            grouped_contest_keys[group].append(contest_key)

    iteration = 0
    renaming_contest_keys = set(contest_keys)
    while contest_keys:
        iteration += 1
        if clear_rating_change:
            qs_clear = base_qs.filter(Q(addition__rating_change__isnull=False) |
                                      Q(addition__new_rating__isnull=False) |
                                      Q(addition__rating__isnull=False))
            for s in qs_clear:
                s.addition.pop('rating', None)
                s.addition.pop('rating_change', None)
                s.addition.pop('new_rating', None)
                s.addition.pop('old_rating', None)
                s.save(update_fields=['addition'])
            clear_rating_change = False

        conditions = (Q(**{f'contest__{field}__in': contest_keys}) for field in fields)
        condition = functools.reduce(operator.__or__, conditions)
        stat_qs = base_qs.filter(condition).select_related('contest')

        total = 0
        for stat in stat_qs:
            contest = stat.contest
            for field in fields:
                key = getattr(contest, field)
                contest_keys.discard(key)
                if not stat.skip_in_stats:
                    renaming_contest_keys.discard(key)

            total += 1
            addition = dict(stat.addition)
            for field in fields:
                key = getattr(contest, field)
                if key in contest_addition_update:
                    ordered_dict = contest_addition_update[key]
                    break

            group = ordered_dict.pop('_group', None)
            if group:
                for contest_key in grouped_contest_keys.pop(group, []):
                    contest_keys.discard(contest_key)
                    renaming_contest_keys.discard(contest_key)

            addition.update(dict(ordered_dict))
            for k, v in ordered_dict.items():
                if v is None:
                    addition.pop(k)
            if to_canonize_str(stat.addition) == to_canonize_str(addition):
                continue
            stat.addition = addition
            stat.save(update_fields=['addition'])

            to_save = False
            contest_fields = contest.info.setdefault('fields', [])
            for k in ordered_dict.keys():
                if k not in contest_fields:
                    contest_fields.append(k)
                    to_save = True
            if to_save:
                if contest.end_time + timedelta(days=31) > timezone.now():
                    next_timing_statistic = timezone.now() + timedelta(minutes=10)
                    if next_timing_statistic < contest.statistic_timing:
                        contest.statistic_timing = next_timing_statistic
                contest.save()
        if iteration > 1 and not total:
            break
        if try_renaming_check and renaming_check(account, renaming_contest_keys, fields, contest_addition_update):
            continue
        if contest_keys:
            out_contests = list(grouped_contest_keys.values()) or contest_keys
            LOG.warning('Not found %d contests for %s = %s', len(out_contests), account, out_contests)
        break


def create_upsolving_statistic(contest, account):
    defaults = {
        'skip_in_stats': True,
        'addition': {'_no_update_n_contests': True},
    }
    if account.name:
        defaults['addition']['name'] = account.name
    stat, created = contest.statistics_set.get_or_create(account=account, defaults=defaults)
    if stat.skip_in_stats:
        return stat, created

    problems = stat.addition.get('problems', {})
    all_upsolving = True
    for solution in problems.values():
        if len(solution) != 1 or 'upsolving' not in solution:
            all_upsolving = False
            break
    if all_upsolving:
        stat.skip_in_stats = True
        stat.addition['_no_update_n_contests'] = True
        stat.save(update_fields=['skip_in_stats', 'addition'])
    return stat, created
