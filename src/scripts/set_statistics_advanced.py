#!/usr/bin/env python3


from pprint import pprint

from django.db.models import Q
from django.utils import timezone
from tqdm import tqdm

from clist.models import Resource
from ranking.models import Statistics
from utils.json_field import JSONF


def run(host=None):
    resources = Resource.objects.order_by('n_accounts')
    if host:
        resources = resources.filter(host__regex=host)
    total = resources.count()

    with tqdm(total=total, desc='resources') as pbar_resource:
        total_info = {}
        for resource in resources.iterator():
            start_time = timezone.now()

            stats = Statistics.objects.filter(account__resource=resource)
            stats = stats.annotate(new_adv=JSONF('addition___advance'))
            stats = stats.exclude(
                (Q(new_adv=False) | Q(new_adv=None)) &
                (Q(addition__advanced=False) | Q(addition__advanced=None))
            )
            stats = stats.exclude(addition___advance__skip=True)
            stats = stats.exclude(advanced=True)
            info = stats.update(advanced=True)

            if info:
                total_info[resource.host] = info

            pbar_resource.set_postfix(
                resource=resource.host,
                time=timezone.now() - start_time,
                info=info,
            )
            pbar_resource.update()
        pbar_resource.close()
        pprint(total_info)
