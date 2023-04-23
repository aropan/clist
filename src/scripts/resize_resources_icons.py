#!/usr/bin/env python3

from clist.models import Resource


def run():
    resources = Resource.objects.all()
    for resource in resources:
        resource.update_icon_sizes()
