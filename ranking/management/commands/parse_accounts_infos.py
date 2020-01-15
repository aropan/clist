#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
from attrdict import AttrDict
from datetime import timedelta
from logging import getLogger
from traceback import format_exc

from tqdm import tqdm
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from clist.models import Resource

from .countrier import Countrier


class Command(BaseCommand):
    help = 'Parsing accounts infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.account')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-q', '--query', default=None, help='regex account key')
        parser.add_argument('-l', '--limit', default=1000, type=int, help='limit users for one resource')

    @staticmethod
    def _get_plugin(module):
        sys.path.append(os.path.dirname(module.path))
        return __import__(module.path.replace('/', '.'), fromlist=['Statistic'])

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        resources = Resource.objects.filter(module__has_accounts_infos_update=True)

        if args.resources:
            filt = Q()
            for r in args.resources:
                filt |= Q(host__iregex=r)
            resources = resources.filter(filt)

        countrier = Countrier()

        now = timezone.now()
        for resource in resources:
            try:
                with transaction.atomic():
                    plugin = self._get_plugin(resource.module)
                    accounts = resource.account_set

                    if args.query:
                        accounts = accounts.filter(key__iregex=args.query)
                    else:
                        accounts = resource.account_set.filter(Q(updated__isnull=True) | Q(updated__lte=now))

                    accounts = list(accounts[:args.limit])
                    users = [a.key for a in accounts]

                    if not users:
                        continue

                    with tqdm(total=len(accounts), desc=f'getting {resource.host}') as pbar:
                        infos = plugin.Statistic.get_users_infos(users=users, pbar=pbar)

                    assert len(accounts) == len(infos)
                    for account, info in zip(accounts, infos):
                        if info is None:
                            self.logger.warning(f'Remove user = {account}')
                            account.delete()
                            continue
                        if info.get('country'):
                            account.country = countrier.get(info['country'])
                        delta = info.pop('delta', timedelta(days=365))
                        account.info.update(info)
                        account.updated = now + delta
                        account.save()
            except Exception:
                self.logger.error(format_exc())
                self.logger.error(f'resource = {resource}')
