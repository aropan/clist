#!/usr/bin/env python3


from django.db.models import F, IntegerField
from django.db.models.functions import Cast

from ranking.models import Account

from utils.json_field import JSONF


def run(*args):
    accounts = Account.objects

    qs = accounts.filter(info__rating__isnull=False)
    qs = qs.annotate(info_rating=Cast(JSONF('info__rating'), IntegerField()))
    qs = qs.exclude(rating=F('info_rating'))
    ret = qs.update(rating=F('info_rating'))
    print(ret)

    qs = accounts.filter(rating__isnull=False)
    qs = qs.annotate(r50=F('rating') / 50)
    qs = qs.exclude(rating50=F('r50'))
    ret = qs.update(rating50=F('r50'))
    print(ret)
