#!/usr/bin/env python3


from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from tqdm import tqdm

from true_coders.models import Coder
from utils.attrdict import AttrDict
from utils.logger import suppress_db_logging_context


class Command(BaseCommand):
    help = 'Set coder n_fields'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('coders.set_coder_n_fields')

    def add_arguments(self, parser):
        parser.add_argument('-c', '--coders', metavar='CODER', nargs='*', help='coder usernames')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        coders = Coder.objects.all()
        if args.coders:
            coders_filters = Q()
            for c in args.coders:
                coders_filters |= Q(username=c)
            coders = coders.filter(coders_filters)

        total_coders = coders.count()

        def set_n_accounts():
            qs = coders.annotate(count=Count('account')).exclude(n_accounts=F('count'))
            total_updates = qs.count()
            if not total_updates:
                return
            total_changes = 0
            self.logger.info(f'Updating n_accounts for {total_updates} of {total_coders} coders')
            with tqdm(total=total_updates, desc='set n_accounts for coders') as pbar:
                with transaction.atomic(), suppress_db_logging_context():
                    for coder in qs.iterator():
                        total_changes += abs(coder.n_accounts - coder.count)
                        coder.n_accounts = coder.count
                        coder.save(update_fields=['n_accounts'])
                        pbar.update()
            self.logger.info(f'Total average changes in n_accounts: {total_changes / total_updates:.2f}')

        def set_n_contests():
            qs = coders.annotate(count=Coalesce(Sum('account__n_contests'), Value(0))).exclude(n_contests=F('count'))
            total_updates = qs.count()
            if not total_updates:
                return
            total_changes = 0
            self.logger.info(f'Updating n_contests for {total_updates} of {total_coders} coders')
            with tqdm(total=total_updates, desc='set n_contests for coders') as pbar:
                with transaction.atomic(), suppress_db_logging_context():
                    for coder in qs.iterator():
                        total_changes += abs(coder.n_contests - coder.count)
                        coder.n_contests = coder.count
                        coder.save(update_fields=['n_contests'])
                        pbar.update()
            self.logger.info(f'Total average changes in n_contests: {total_changes / total_updates:.2f}')

        def set_n_subscribers():
            qs = coders.annotate(count=Count('subscribers')).exclude(n_subscribers=F('count'))
            total_updates = qs.count()
            if not total_updates:
                return
            total_changes = 0
            self.logger.info(f'Updating n_subscribers for {total_updates} of {total_coders} coders')
            with tqdm(total=total_updates, desc='set n_subscribers for coders') as pbar:
                with transaction.atomic(), suppress_db_logging_context():
                    for coder in qs.iterator():
                        total_changes += abs(coder.n_subscribers - coder.count)
                        coder.n_subscribers = coder.count
                        coder.save(update_fields=['n_subscribers'])
                        pbar.update()
            self.logger.info(f'Total average changes in n_subscribers: {total_changes / total_updates:.2f}')

        set_n_accounts()
        set_n_contests()
        set_n_subscribers()
