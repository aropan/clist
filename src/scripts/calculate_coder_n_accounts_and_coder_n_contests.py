#!/usr/bin/env python3

from django.db import transaction
from django.db.models import Count, F, Sum, Value
from django.db.models.functions import Coalesce
from tqdm import tqdm

from true_coders.models import Coder


def run(*args):
    qs = Coder.objects.annotate(count=Count('account')).exclude(n_accounts=F('count'))
    total = qs.count()
    with tqdm(total=total, desc='calculating n_accounts for coders') as pbar:
        with transaction.atomic():
            for c in qs.iterator():
                c.n_accounts = c.count
                c.save()
                pbar.update()

    qs = Coder.objects.annotate(count=Coalesce(Sum('account__n_contests'), Value(0))).exclude(n_contests=F('count'))
    total = qs.count()
    with tqdm(total=total, desc='calculating n_contests for coders') as pbar:
        with transaction.atomic():
            for c in qs.iterator():
                c.n_contests = c.count
                c.save()
                pbar.update()
