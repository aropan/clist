#!/usr/bin/env python3


import fire
from django.db import transaction
from django.db.models import Q
from tqdm import tqdm

from ranking.models import Account
from clist.models import Contest
from clist.views import update_writers


def main(host=None):
    with transaction.atomic():
        print(Account.objects.filter(~Q(n_writers=0)).update(n_writers=0))
        print(Contest.writers.through.objects.all().delete())
        qs = Contest.objects.filter(info__writers__isnull=False)
        for contest in tqdm(qs.iterator(), total=qs.count()):
            update_writers(contest)


def run(*args):
    fire.Fire(main, args)
