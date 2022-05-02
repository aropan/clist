#!/usr/bin/env python3

import fire
from tqdm import tqdm

from clist.models import Resource


def main(host=None):
    resources = Resource.objects.all()
    if host:
        resources = resources.filter(host__regex=host)

    for resource in tqdm(resources.iterator(), total=resources.count()):
        ratings = []
        qs = resource.account_set.filter(rating__isnull=False)
        min_n_participations = resource.info.get('default_variables', {}).get('min_n_participations')
        if min_n_participations is not None:
            qs = qs.filter(n_contests__gte=min_n_participations)
        qs = qs.values('rating')
        for rating in tqdm(qs.iterator(), total=qs.count()):
            ratings.append(rating['rating'])
        if ratings:
            avg_rating = sum(ratings) / len(ratings)
            print(resource, avg_rating)
            resource.avg_rating = avg_rating
            resource.save()


def run(*args):
    fire.Fire(main, args)
