#!/usr/bin/env python3

from collections import defaultdict

import fire
from flatten_dict import flatten
from flatten_dict.reducers import make_reducer
from tqdm import tqdm

from clist.models import Resource
from ranking.models import Account


def main(host=None):
    resources = Resource.objects.all()
    if host:
        resources = resources.filter(host__regex=host)

    total = Account.objects.filter(resource__in=resources).count()

    with tqdm(total=total, desc='accounts') as pbar:
        for resource in resources.iterator():
            fields_types = defaultdict(set)
            pbar.set_postfix(resource=resource)

            for info in resource.account_set.values('info').iterator():
                info = info['info']
                info = flatten(info, reducer=make_reducer(delimiter='__'))
                for k, v in info.items():
                    if Account.is_special_info_field(k) or '___' in k:
                        continue
                    fields_types[k].add(type(v).__name__)
                pbar.update()
            fields_types = {k: list(v) for k, v in fields_types.items()}
            resource.accounts_fields['types'] = fields_types
            resource.save()


def run(*args):
    fire.Fire(main, args)
