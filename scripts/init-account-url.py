#!/usr/bin/env python3

from django.db.models.signals import m2m_changed
from django.db import transaction
from tqdm import tqdm

from ranking.models import Account, update_account_url


def run(*args):
    qs = Account.objects.filter(url__isnull=True)
    total = qs.count()
    with tqdm(total=total) as pbar:
        while True:
            with transaction.atomic():
                batch = 0
                for a in qs.select_related('resource').prefetch_related('coders').iterator():
                    update_account_url(m2m_changed, a, action='post_save')
                    pbar.update()
                    batch += 1
                    if batch == 10000:
                        break
                if batch == 0:
                    break
