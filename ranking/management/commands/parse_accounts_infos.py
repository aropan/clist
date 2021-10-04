#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from datetime import timedelta
from logging import getLogger

from attrdict import AttrDict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django_super_deduper.merge import MergedModelInstance
from tqdm import tqdm
from traceback_with_variables import format_exc

from clist.models import Resource
from ranking.management.commands.common import account_update_contest_additions
from ranking.management.commands.countrier import Countrier
from ranking.models import Account
from true_coders.models import Coder


class Command(BaseCommand):
    help = 'Parsing accounts infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.account')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-q', '--query', default=None, help='regex account key')
        parser.add_argument('-f', '--force', action='store_true', help='get accounts with min updated time')
        parser.add_argument('-l', '--limit', default=None, type=int,
                            help='limit users for one resource (default is 1000)')

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
            accounts = resource.account_set

            if args.query:
                accounts = accounts.filter(Q(key__iregex=args.query) | Q(name__iregex=args.query))
            elif args.force:
                accounts = accounts.order_by('updated')
            else:
                accounts = accounts.filter(Q(updated__isnull=True) | Q(updated__lte=now))

            count, total = 0, accounts.count()
            resource_info = resource.info.get('accounts', {})
            if args.limit or not resource_info.get('nolimit', False) or resource_info.get('limit'):
                limit = resource_info.get('limit') or args.limit or 1000
                accounts = accounts[:limit]
            accounts = list(accounts)

            if not accounts:
                continue

            try:
                with tqdm(total=len(accounts), desc=f'getting {resource.host} (total = {total})') as pbar:
                    infos = resource.plugin.Statistic.get_users_infos(
                        users=[a.key for a in accounts],
                        resource=resource,
                        accounts=accounts,
                        pbar=pbar,
                    )

                    for account, data in zip(accounts, infos):
                        with transaction.atomic():
                            if data.get('skip'):
                                delta = data.get('delta')
                                if delta:
                                    count += 1
                                    account.updated = now + delta
                                    account.save()
                                continue
                            count += 1
                            info = data['info']
                            if info is None:
                                _, info = account.delete()
                                info = {k: v for k, v in info.items() if v}
                                pbar.set_postfix(warning=f'Remove user {account} = {info}')
                                continue

                            params = data.pop('contest_addition_update_params', {})
                            contest_addition_update = data.pop('contest_addition_update', params.pop('update', {}))
                            contest_addition_update_by = data.pop('contest_addition_update_by', params.pop('by', None))
                            if contest_addition_update or params.get('clear_rating_change'):
                                account_update_contest_additions(
                                    account,
                                    contest_addition_update,
                                    timedelta_limit=timedelta(days=31) if account.info and not has_param else None,
                                    by=contest_addition_update_by,
                                    **params,
                                )

                            if 'rename' in data:
                                other, created = Account.objects.get_or_create(resource=account.resource,
                                                                               key=data['rename'])
                                new = MergedModelInstance.create(other, [account])
                                account.delete()
                                account = new
                                account.save()

                            coders = data.pop('coders', [])
                            if coders:
                                qs = Coder.objects \
                                    .filter(account__resource=resource, account__key__in=coders) \
                                    .exclude(account=account)
                                for c in qs:
                                    account.coders.add(c)

                            if info.get('country'):
                                account.country = countrier.get(info['country'])
                            if info.get('name'):
                                account.name = info['name']
                            if 'rating' in info:
                                info['_rating_time'] = int(now.timestamp())
                            delta = info.pop('delta', timedelta(days=365))
                            if data.get('replace_info'):
                                for k, v in account.info.items():
                                    if k.endswith('_') and k not in info:
                                        info[k] = v
                                account.info = info
                            else:
                                account.info.update(info)
                            account.updated = now + delta
                            account.save()
            except Exception:
                if not has_param:
                    for account in tqdm(accounts, desc='changing update time'):
                        account.updated = now + timedelta(days=1)
                        account.save()
                self.logger.error(f'resource = {resource}')
                self.logger.error(format_exc())
            self.logger.info(f'Parsed accounts infos (resource = {resource}): {count} of {total}')
