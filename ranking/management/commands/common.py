import tqdm

from ranking.models import Statistics
from django.utils import timezone


def account_update_contest_additions(account, contest_addition_update, timedelta_limit=None):
    contest_keys = set(contest_addition_update.keys())
    qs = Statistics.objects \
        .filter(account=account, contest__key__in=contest_keys) \
        .select_related('contest')
    if timedelta_limit is not None:
        qs.filter(modified__lte=timezone.now() - timedelta_limit)

    for stat in tqdm.tqdm(qs, desc=f'updating additions for {account.key}', position=1):
        addition = dict(stat.addition)
        ordered_dict = contest_addition_update[stat.contest.key]
        addition.update(dict(ordered_dict))
        stat.addition = addition
        stat.save()

        to_save = False
        for k in ordered_dict.keys():
            if k not in stat.contest.info['fields']:
                stat.contest.info['fields'].append(k)
                to_save = True
        if to_save:
            stat.contest.save()
