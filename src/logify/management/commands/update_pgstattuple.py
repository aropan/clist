#!/usr/bin/env python3

import re
from logging import getLogger

import tqdm
from django.core.management.base import BaseCommand
from django.db import connection

from logify.models import PgStatTuple
from utils.attrdict import AttrDict
from utils.db import dictfetchone, find_app_by_table


class Command(BaseCommand):
    help = 'Updates the PgStatTuple table with fresh data from pgstattuple'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('logify.update_pgstattuple')

    def add_arguments(self, parser):
        parser.add_argument('-n', '--limit', type=int, help='number of tables')
        parser.add_argument('-f', '--search', type=str, help='search tables')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            tables = [row[0] for row in cursor.fetchall()]
            if args.limit:
                tables = tables[:args.limit]
            if args.search:
                tables = [table for table in tables if re.search(args.search, table)]

            for table in tqdm.tqdm(tables, desc='tables'):
                cursor.execute(f"SELECT * FROM pgstattuple('{table}')")
                stats = dictfetchone(cursor)
                defaults = {'app_name': find_app_by_table(table), **stats}
                PgStatTuple.objects.update_or_create(table_name=table, defaults=defaults)
