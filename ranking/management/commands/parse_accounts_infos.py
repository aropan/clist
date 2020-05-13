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
from django_super_deduper.merge import MergedModelInstance

from clist.models import Resource
from ranking.models import Account
from true_coders.models import Coder

from ranking.management.commands.countrier import Countrier
from ranking.management.commands.common import account_update_contest_additions


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

        has_param = args.resources or args.query or args.limit

        if args.resources:
            filt = Q()
            for r in args.resources:
                filt |= Q(host__iregex=r)
            resources = Resource.objects.filter(filt)
        else:
            resources = Resource.objects.filter(module__has_accounts_infos_update=True)

        countrier = Countrier()

        now = timezone.now()
        for resource in resources:
            with transaction.atomic():
                plugin = self._get_plugin(resource.module)
                accounts = resource.account_set

                if args.query:
                    accounts = accounts.filter(key__iregex=args.query)
                else:
                    accounts = accounts.filter(Q(updated__isnull=True) | Q(updated__lte=now))

                total = accounts.count()
                accounts = list(accounts[:args.limit])

                if not accounts:
                    continue

                try:
                    with tqdm(total=len(accounts), desc=f'getting {resource.host} (total = {total})') as pbar:
                        infos = plugin.Statistic.get_users_infos(
                            users=[a.key for a in accounts],
                            resource=resource,
                            accounts=accounts,
                            pbar=pbar,
                        )

                        for account, data in zip(accounts, infos):
                            info = data['info']
                            if info is None:
                                _, info = account.delete()
                                info = {k: v for k, v in info.items() if v}
                                pbar.set_postfix(warning=f'Remove user {account} = {info}')
                                continue

                            contest_addition_update = data.pop('contest_addition_update', {})
                            contest_addition_update_by = data.pop('contest_addition_update_by', None)
                            if contest_addition_update:
                                account_update_contest_additions(
                                    account,
                                    contest_addition_update,
                                    timedelta_limit=timedelta(days=31) if account.info and not has_param else None,
                                    by=contest_addition_update_by,
                                )

                            if 'rename' in data:
                                other, created = Account.objects.get_or_create(resource=account.resource,
                                                                               key=data['rename'])
                                if not created:
                                    new = MergedModelInstance.create(other, [account])
                                    account.delete()
                                else:
                                    new = MergedModelInstance.create(account, [other])
                                    other.delete()
                                account = new

                            coders = data.pop('coders', [])
                            if coders:
                                qs = Coder.objects \
                                    .filter(account__resource=resource, account__key__in=coders) \
                                    .exclude(account=account)
                                for c in qs:
                                    account.coders.add(c)

                            if info.get('country'):
                                account.country = countrier.get(info['country'])
                            if info.get('rating'):
                                info['rating_ts'] = int(now.timestamp())
                            delta = info.pop('delta', timedelta(days=365))
                            account.info.update(info)
                            account.updated = now + delta
                            account.save()
                except Exception:
                    if not has_param:
                        for account in tqdm(accounts, desc='changing update time'):
                            account.updated = now + timedelta(days=1)
                            account.save()
                    self.logger.error(format_exc())
                    self.logger.error(f'resource = {resource}')
