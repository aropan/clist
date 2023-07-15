import functools
import json
import operator
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ranking.models import Statistics


def to_canonize_str(data):
    return json.dumps(data, sort_keys=True)


def account_update_contest_additions(
    account,
    contest_addition_update,
    timedelta_limit=None,
    by=None,
    clear_rating_change=None,
):
    contest_keys = set(contest_addition_update.keys())

    fields = 'key' if by is None else by
    if isinstance(fields, str):
        fields = [fields]

    qs = Statistics.objects.filter(account=account)
    if timedelta_limit is not None and not clear_rating_change:
        qs.filter(modified__lte=timezone.now() - timedelta_limit)

    if clear_rating_change:
        qs_clear = qs.filter(Q(addition__rating_change__isnull=False) | Q(addition__new_rating__isnull=False))
        for s in qs_clear:
            s.addition.pop('rating_change', None)
            s.addition.pop('new_rating', None)
            s.addition.pop('old_rating', None)
            s.save()

    conditions = (Q(**{f'contest__{field}__in': contest_keys}) for field in fields)
    condition = functools.reduce(operator.__or__, conditions)
    qs = qs.filter(condition).select_related('contest')

    total = 0
    for stat in qs:
        contest = stat.contest
        total += 1
        addition = dict(stat.addition)
        for field in fields:
            key = getattr(contest, field)
            if key in contest_addition_update:
                ordered_dict = contest_addition_update[key]
                break
        addition.update(dict(ordered_dict))
        for k, v in ordered_dict.items():
            if v is None:
                addition.pop(k)
        if to_canonize_str(stat.addition) == to_canonize_str(addition):
            continue
        stat.addition = addition
        stat.save()

        to_save = False
        for k in ordered_dict.keys():
            contest_fields = contest.info.setdefault('fields', [])
            if k not in contest_fields:
                contest_fields.append(k)
                to_save = True
        if to_save:
            if contest.end_time + timedelta(days=31) > timezone.now():
                next_timing_statistic = timezone.now() + timedelta(minutes=10)
                if next_timing_statistic < contest.statistic_timing:
                    contest.statistic_timing = next_timing_statistic
            contest.save()


def create_upsolving_statistic(contest, account):
    defaults = {'skip_in_stats': True, 'addition': {'_no_update_n_contests': True}}
    stat, created = contest.statistics_set.get_or_create(account=account, defaults=defaults)
    return stat, created
