#!/usr/bin/env python3

from django.db import transaction
from django_super_deduper.merge import MergedModelInstance

from ranking.models import AccountRenaming
from utils.math import max_with_none


@transaction.atomic
def rename_account(account, other):
    AccountRenaming.objects.update_or_create(
        resource=account.resource,
        old_key=account.key,
        defaults={'new_key': other.key},
    )
    AccountRenaming.objects.filter(
        resource=account.resource,
        old_key=other.key,
    ).delete()

    n_contests = other.n_contests + account.n_contests
    n_writers = other.n_writers + account.n_writers
    last_activity = max_with_none(account.last_activity, other.last_activity)
    last_submission = max_with_none(account.last_submission, other.last_submission)
    new = MergedModelInstance.create(other, [account])
    account.delete()
    account = new
    account.n_contests = n_contests
    account.n_writers = n_writers
    account.last_activity = last_activity
    account.last_submission = last_submission
    account.save()
    return account


def clear_problems_fields(problems):
    if not problems:
        return
    for v in problems.values():
        if not isinstance(v, dict):
            continue
        v.pop('first_ac', None)
        v.pop('first_ac_of_all', None)
