#!/usr/bin/env python3

from django.db import transaction
from django.db.models import Count
from tqdm import tqdm

from true_coders.models import Coder


def run(*args):
    qs = Coder.objects
    qs = qs.annotate(count=Count('account'))
    total = qs.count()
    with tqdm(total=total, desc='calculating coders') as pbar:
        with transaction.atomic():
            for c in qs.iterator():
                c.n_accounts = c.count
                c.save()
                pbar.update()
