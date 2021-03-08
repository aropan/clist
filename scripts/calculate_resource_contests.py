#!/usr/bin/env python3

from tqdm import tqdm

from clist.models import Contest, Resource
from ranking.models import Account


def run(*args):
    resources = Resource.objects.all()
    total = resources.count()

    for resource in tqdm(resources.iterator(), total=total, desc='contests'):
        count = Contest.objects.filter(resource=resource).count()
        if count != resource.n_contests:
            print(resource, resource.n_contests, count)
            resource.n_contests = count
            resource.save()

    with tqdm(total=total, desc='accounts') as pbar:
        for resource in resources.iterator():
            pbar.set_postfix(resource=resource)
            count = Account.objects.filter(resource=resource).count()
            if count != resource.n_accounts:
                print(resource, resource.n_accounts, count)
                resource.n_accounts = count
                resource.save()
            pbar.update()
