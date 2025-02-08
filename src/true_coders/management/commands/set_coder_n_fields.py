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

        def set_n_field(count_annotation, count_field):
            qs = coders.annotate(count=count_annotation).exclude(**{count_field: F('count')})
            total_updates = qs.count()
            if not total_updates:
                return
            total_changes = 0
            self.logger.info(f'Updating {count_field} for {total_updates} of {total_coders} coders')
            with tqdm(total=total_updates, desc='set {count_field} for coders') as pbar:
                with transaction.atomic(), suppress_db_logging_context():
                    for coder in qs.iterator():
                        total_changes += abs(getattr(coder, count_field) - coder.count)
                        setattr(coder, count_field, coder.count)
                        coder.save(update_fields=[count_field])
                        pbar.update()
            self.logger.info(f'Total average changes in {count_field}: {total_changes / total_updates:.2f}')

        set_n_field(Count('account'), 'n_accounts')
        set_n_field(Coalesce(Sum('account__n_contests'), Value(0)), 'n_contests')
        set_n_field(Count('subscribers'), 'n_subscribers')
        set_n_field(Count('listvalue'), 'n_listvalues')
