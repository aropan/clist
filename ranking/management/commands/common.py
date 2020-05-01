import tqdm
import json

from ranking.models import Statistics
from django.utils import timezone


def to_canonize_str(data):
    return json.dumps(data, sort_keys=True)


def account_update_contest_additions(account, contest_addition_update, timedelta_limit=None, by=None):
    contest_keys = set(contest_addition_update.keys())
    field = 'key' if by is None else by
    qs = Statistics.objects \
        .filter(account=account) \
        .filter(**{f'contest__{field}__in': contest_keys}) \
        .select_related('contest')
    if timedelta_limit is not None:
        qs.filter(modified__lte=timezone.now() - timedelta_limit)

    total = 0
    for stat in tqdm.tqdm(qs, desc=f'updating additions for {account.key}', position=1):
        total += 1
        addition = dict(stat.addition)
        ordered_dict = contest_addition_update[getattr(stat.contest, field)]
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
            if k not in stat.contest.info['fields']:
                stat.contest.info['fields'].append(k)
                to_save = True
        if to_save:
            stat.contest.save()
