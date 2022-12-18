#!/usr/bin/env python3


from django.utils import timezone
from tqdm import tqdm

from clist.models import Resource


def run(host=None):
    resources = Resource.objects.order_by('n_accounts')
    if host:
        resources = resources.filter(host__regex=host)
    total = resources.count()

    with tqdm(total=total, desc='resources') as pbar_resource:
        for resource in resources.iterator():
            start_time = timezone.now()
            accounts = resource.account_set.all()

            accounts = accounts.filter(
                coders__isnull=True,
                statistics__isnull=True,
                writer_set__isnull=True,
            )

            n_clean_accounts = accounts.delete()

            pbar_resource.set_postfix(
                resource=resource.host,
                n_clean_accounts=n_clean_accounts,
                time=timezone.now() - start_time,
            )
            pbar_resource.update()
        pbar_resource.close()
