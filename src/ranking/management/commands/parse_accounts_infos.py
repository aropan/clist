#!/usr/bin/env python
# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import timedelta
from logging import getLogger

import arrow
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.utils import timezone
from tailslide import Percentile
from tqdm import tqdm

from clist.models import Resource
from logify.models import EventLog, EventStatus
from ranking.models import Account
from ranking.utils import account_update_contest_additions, rename_account
from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.countrier import Countrier
from utils.traceback_with_vars import colored_format_exc


def add_dict_to_dict(src, dst):
    for k, v in src.items():
        if k not in dst:
            dst[k] = v
        elif isinstance(v, set):
            dst[k] |= v
        elif isinstance(v, dict):
            dst[k].update(v)
        else:
            dst[k] += v


class Command(BaseCommand):
    help = 'Parsing accounts infos'

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger('ranking.parse.account')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='host name for update')
        parser.add_argument('-q', '--query', default=None, nargs='+', help='account key or name')
        parser.add_argument('-f', '--force', action='store_true', help='get accounts with min updated time')
        parser.add_argument('-l', '--limit', default=None, type=int,
                            help='limit users for one resource (default is 1000)')
        parser.add_argument('-a', '--all', action='store_true', help='get all accounts and create if needed')
        parser.add_argument('-t', '--top', action='store_true', help='top accounts priority')
        parser.add_argument('-cid', '--contest-id', default=None, type=int, help='accounts from contest')
        parser.add_argument('--update-new-year', action='store_true', help='force update new year accounts')
        parser.add_argument('--min-rating', default=None, type=int, help='minimum rating')
        parser.add_argument('--min-n-contests', default=None, type=int, help='minimum number of contests')
        parser.add_argument('--without-new', action='store_true', help='only parsed account')
        parser.add_argument('--with-field', default=None, type=str, help='only parsed account which have field')
        parser.add_argument('--reset-upsolving', action='store_true', help='reset upsolving')
        parser.add_argument('--with-coders', action='store_true', help='with coders')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        has_custom_params = args.resources or args.query or args.limit or args.all
        regular_update = not has_custom_params

        if args.resources:
            resources = Resource.objects
            filt = Q()
            for r in args.resources:
                filt |= Q(host__iregex=r)
            resources = resources.filter(filt)
        else:
            resources = Resource.available_for_update_objects
            resources = resources.filter(has_accounts_infos_update=True)

        countrier = Countrier()

        now = timezone.now()
        n_total_counter = defaultdict(int)
        n_resource = 0
        for resource in resources:
            resource_info = resource.info.get('accounts', {})
            if resource_info.get('skip'):
                continue

            if args.all:
                accounts = []
                total = 0
            else:
                accounts = resource.account_set

                if args.query:
                    condition = Q()
                    for query in args.query:
                        condition |= Q(key=query) | Q(name=query)
                    accounts = accounts.filter(condition)
                elif not args.force:
                    condition = Q(updated__isnull=False, updated__lte=now)
                    if resource_info.get('force_on_new_year') or args.update_new_year:
                        days = abs(now - now.replace(month=1, day=1)).days
                        days = min(364 - days, days)
                        if days <= 14 or args.update_new_year:
                            new_year_condition = Q(coders__isnull=False)

                            rating95 = accounts.aggregate(rating95=Percentile('rating', .95))['rating95']
                            if rating95 is not None:
                                new_year_condition |= Q(rating__gt=rating95)

                            if args.update_new_year:
                                update = accounts.filter(new_year_condition).exclude(condition).update(updated=now)
                                self.logger.info(f'update new year = {update}')
                                return

                            condition |= new_year_condition & Q(modified__lt=now - timedelta(days=1))

                    accounts = accounts.filter(condition)

                if args.min_rating:
                    accounts = accounts.filter(rating__gte=args.min_rating)
                if args.min_n_contests:
                    accounts = accounts.filter(n_contests__gte=args.min_n_contests)
                if args.without_new:
                    accounts = accounts.exclude(info__exact={})
                if args.with_field:
                    accounts = accounts.filter(**{f'info__{args.with_field}__isnull': False})
                if args.contest_id:
                    accounts = accounts.filter(statistics__contest_id=args.contest_id)
                if args.with_coders:
                    accounts = accounts.filter(coders__isnull=False)

                total = accounts.count()
                if not total:
                    continue

                accounts = accounts.annotate(has_coders=Case(
                    When(coders__isnull=False, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                ))
                order = ['-has_coders', 'updated']
                if args.top:
                    order = [F('rating').desc(nulls_last=True)] + order
                elif args.contest_id:
                    order = ['statistics__place_as_int'] + order
                elif args.limit:
                    order = ['updated']
                accounts = accounts.order_by(*order)

                if args.limit or not resource_info.get('nolimit', False) or resource_info.get('limit'):
                    limit = args.limit or resource_info.get('limit') or 1000
                    accounts = accounts[:limit]
                accounts = list(accounts)

                if not accounts:
                    continue

            event_log = EventLog.objects.create(name='parse_accounts_infos',
                                                related=resource,
                                                status=EventStatus.IN_PROGRESS,
                                                message=f'{len(accounts)} of {total} accounts')
            count = 0
            n_counter = defaultdict(int)
            update_submissions_info = {}
            account = None
            exception_error = None
            seen = set()
            n_accounts_to_update = total
            try:
                with tqdm(total=len(accounts), desc=f'getting {resource.host} (total = {total})') as pbar:
                    infos = resource.plugin.Statistic.get_users_infos(
                        users=[a.key for a in accounts],
                        resource=resource,
                        accounts=accounts,
                        pbar=pbar,
                    )

                    if args.all:
                        def inf_none():
                            while True:
                                yield None
                        accounts = inf_none()

                    for account, data in zip(accounts, infos):
                        if args.all:
                            member = data.pop('member')
                            account, created = Account.objects.get_or_create(key=member, resource=resource)
                        else:
                            account.refresh_from_db()
                        is_team = account.info.get('is_team', False)
                        do_upsolve = resource.has_upsolving and account.has_coders and not is_team
                        n_accounts_to_update -= 1
                        with transaction.atomic():
                            if 'delta' in data or 'delta' in (data.get('info') or {}):
                                n_counter['deferred'] += 1
                            if data.get('skip'):  # skip to update after
                                delta = data.get('delta') or timedelta(days=100)
                                n_counter['skip'] += 1
                                account.updated = now + delta
                                account.save(update_fields=['updated'])
                                seen.add(account.key)
                                continue

                            if (deleted := data.get('delete', False)) != account.deleted:
                                account.deleted = deleted
                                account.save(update_fields=['deleted'])
                            if account.deleted:
                                if 'coder' in data:
                                    account.coders.filter(username=data['coder']).delete()
                                n_counter['deleted'] += 1
                                account.updated = now + timedelta(days=365)
                                account.save(update_fields=['deleted', 'updated'])
                                if not resource.accountrenaming_set.filter(old_key=account.key).exists():
                                    deleted_count, _ = resource.accountrenaming_set.filter(new_key=account.key).delete()
                                    if deleted_count:
                                        n_counter['deleted_renaming'] += deleted_count
                                seen.add(account.key)
                                continue

                            count += 1
                            info = data['info']

                            params = data.pop('contest_addition_update_params', {})
                            contest_addition_update = data.pop('contest_addition_update', params.pop('update', {}))
                            contest_addition_update_by = data.pop('contest_addition_update_by', params.pop('by', None))
                            if contest_addition_update or params.get('clear_rating_change'):
                                account_update_contest_additions(
                                    account,
                                    contest_addition_update,
                                    timedelta_limit=timedelta(days=31) if account.info and regular_update else None,
                                    by=contest_addition_update_by,
                                    **params,
                                )

                            if 'rename' in data:
                                other, _ = Account.objects.get_or_create(resource=account.resource, key=data['rename'])
                                n_counter['rename'] += 1
                                pbar.set_postfix(rename=f'{n_counter["rename"]}: Rename {account} to {other}')
                                account = rename_account(account, other)

                            coders = data.pop('coders', [])
                            if coders:
                                qs = Coder.objects \
                                    .filter(account__resource=resource, account__key__in=coders) \
                                    .exclude(account=account)
                                for c in qs:
                                    account.coders.add(c)

                            if do_upsolve:
                                if args.reset_upsolving:
                                    account.info.pop('submissions_', None)
                                updated_info = resource.plugin.Statistic.update_submissions(account=account,
                                                                                            resource=resource)
                                add_dict_to_dict(updated_info, update_submissions_info)

                                coders = list(account.coders.values_list('username', flat=True))
                                if coders and updated_info.get('n_updated'):
                                    call_command('fill_coder_problems', coders=coders, resources=[resource.host])

                            if info.get('country'):
                                account.country = countrier.get(info['country'])
                            if 'name' in info:
                                name = info['name']
                                account.name = name if name and name != account.key else None
                            if 'rating' in info and account.info.get('rating') != info['rating']:
                                info['_rating_time'] = int(now.timestamp())
                            delta = timedelta(**resource_info.get('delta', {'days': 365}))
                            delta = info.pop('delta', delta)

                            extra = info.pop('data_', {})
                            if isinstance(extra, dict):
                                for k, v in extra.items():
                                    if k not in info and not Account.is_special_info_field(k):
                                        info[k] = v

                            for k, v in account.info.items():
                                if args.all or k not in info and Account.is_special_info_field(k):
                                    info[k] = v

                            outdated = account.info.pop('outdated_', {})
                            outdated.update(account.info)
                            for k in info.keys():
                                if k in outdated:
                                    outdated.pop(k)
                            info['outdated_'] = outdated

                            account.info = info

                            if do_upsolve and account.last_submission is not None:
                                sumission_delta = max(now - account.last_submission, timedelta(hours=20))
                                delta = min(delta, sumission_delta)

                            account.updated = arrow.get(now + delta).ceil('day').datetime
                            account.save()
                            seen.add(account.key)
            except Exception as e:
                exception_error = str(e)
                self.logger.debug(colored_format_exc())
                self.logger.warning(f'resource = {resource}')
                self.logger.error(f'Parse accounts infos: {e}')

            if regular_update and n_accounts_to_update != resource.n_accounts_to_update:
                resource.n_accounts_to_update = n_accounts_to_update
                resource.save(update_fields=['n_accounts_to_update'])

            message = f'{count} of {total} accounts, {dict(n_counter)}'
            if exception_error:
                event_log.update_status(EventStatus.FAILED, message=exception_error)
            else:
                event_log.update_status(EventStatus.COMPLETED, message=message)

            if regular_update:
                try:
                    updated = arrow.get(now + timedelta(days=1)).ceil('day').datetime
                    for a in tqdm(accounts, desc='changing update time'):
                        if a.key not in seen:
                            a.updated = updated
                            a.save(update_fields=['updated'])
                except Exception as e:
                    self.logger.debug(colored_format_exc())
                    self.logger.error(f'Parse accounts infos changing update time: {e}')

            self.logger.info(f'Parsed accounts infos (resource = {resource}): {message}')
            if update_submissions_info:
                self.logger.info(f'Update submissions info: {update_submissions_info}')
                n_counter['update_submissions_info'] = update_submissions_info
            n_resource += 1
            n_counter['resource'] += 1
            add_dict_to_dict(n_counter, n_total_counter)

        total_update_submissions_info = n_total_counter.pop('update_submissions_info', {})
        self.logger.info(f'Total: {dict(n_total_counter)}')
        if total_update_submissions_info:
            self.logger.info(f'Total update submissions info: {total_update_submissions_info}')
