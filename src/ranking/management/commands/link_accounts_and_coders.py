#!/usr/bin/env python3

import logging
import re
from collections import Counter, defaultdict

import coloredlogs
import tqdm
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from clist.models import Contest
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception
from notification.models import NotificationMessage
from ranking.models import Account, AccountMatching, MatchingStatus, Statistics
from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.logger import suppress_db_logging_context

logger = logging.getLogger(__name__)
coloredlogs.install(logger=logger)


class Command(BaseCommand):
    help = 'Link accounts and coders'

    def add_arguments(self, parser):
        parser.add_argument('--contest-id', '-cid', type=int, help='Contest id')
        parser.add_argument('--name-query', '-q', type=str, help='Name query')
        parser.add_argument('--link', '-l', action='store_true', help='Link accounts and coders')

    def process(self, args, contest):
        resource = contest.resource
        statistics = Statistics.objects.filter(contest_id=args.contest_id)
        statistics = statistics.order_by(*contest.get_statistics_order())
        statistics = statistics.select_related('account')
        counter = defaultdict(int)
        for statistic in tqdm.tqdm(statistics, total=statistics.count(), desc='statistics'):
            statistic_updated_fields = set()
            statistic_account = statistic.account
            members = statistic.addition.get('_members')
            if not members:
                counter['no_members'] += 1
                continue
            members = [m for m in members if m.get('name')]
            for member in members:
                name = member['name']
                if args.name_query and not re.search(args.name_query, name, re.I):
                    counter['skip_name_query'] += 1
                    continue

                if 'account' in member:
                    member_account = resource.account_set.filter(key=member['account']).first()
                    if member_account is None:
                        counter['skip_account_none'] += 1
                        continue
                    if member_account != statistic_account:
                        counter['skip_account_diff'] += 1
                        continue
                account = statistic_account

                is_handle = ' ' not in name
                matching_data = dict(
                    name=name,
                    account=account,
                    statistic=statistic,
                    contest=contest,
                    resource=resource,
                )
                if is_handle and account.name != name:
                    counter['skip_handle'] += 1
                    with suppress_db_logging_context():
                        AccountMatching.objects.filter(**matching_data).delete()
                    continue

                with suppress_db_logging_context(), transaction.atomic():
                    matching, _ = AccountMatching.objects.get_or_create(**matching_data)

                    if matching.status != MatchingStatus.NEW:
                        counter[f'skip_status_{matching.status}'] += 1
                        continue

                    accounts_filter = Q(key=name)
                    if not is_handle:
                        accounts_filter |= Q(name=name)
                    accounts = Account.objects.filter(accounts_filter)
                    accounts = accounts.filter(Q(info__is_team__isnull=True) | Q(info__is_team=False))
                    n_accounts = accounts.count()

                    coders = Coder.objects.filter(account__in=accounts)
                    coders_counter = Counter(coders)
                    n_coders = sum(coders_counter.values())
                    n_different_coders = len(coders_counter)
                    if n_different_coders == 1:
                        coder = next(iter(coders_counter))
                    else:
                        coder = None

                    updates = {
                        'n_found_accounts': n_accounts,
                        'n_found_coders': n_coders,
                        'n_different_coders': n_different_coders,
                        'coder': coder,
                    }

                    if coder is not None:
                        if args.link and member.get('coder') != coder.username:
                            counter['set_coder'] += 1
                            member['coder'] = coder.username
                            statistic_updated_fields.add('addition')
                        if not args.link:
                            counter['skip_link'] += 1
                        elif account.coders.filter(pk=coder.pk).exists():
                            counter['already_linked'] += 1
                            updates['status'] = MatchingStatus.ALREADY
                        else:
                            account.coders.add(coder)
                            message = f'Source <a href="{contest.actual_url}">{contest.title}</a>.'
                            NotificationMessage.link_accounts(to=coder, accounts=[account], message=message)
                            updates['status'] = MatchingStatus.DONE

                    update_fields = []
                    for key, value in updates.items():
                        if getattr(matching, key) != value:
                            update_fields.append(key)
                            setattr(matching, key, value)
                    if update_fields:
                        matching.save(update_fields=update_fields)
                        counter['update'] += 1
                    else:
                        counter['skip'] += 1
            if statistic_updated_fields:
                statistic.save(update_fields=list(statistic_updated_fields))

        if args.link:
            contest.set_matched_coders_to_members = True
            contest.save(update_fields=['set_matched_coders_to_members'])

        for key, value in sorted(counter.items()):
            logger.info(f'{key}: {value}')

        return dict(counter)

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)
        contest = Contest.objects.select_related('resource').get(pk=args.contest_id)

        event_log = EventLog.objects.create(name='link_accounts_and_coders',
                                            related=contest,
                                            status=EventStatus.IN_PROGRESS)
        with failed_on_exception(event_log):
            message = self.process(args, contest)
        event_log.update_status(EventStatus.COMPLETED, message=message)
