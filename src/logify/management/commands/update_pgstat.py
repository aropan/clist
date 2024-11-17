#!/usr/bin/env python3

import re
from logging import getLogger

import tqdm
from django.core.management.base import BaseCommand
from django.db import connection

from logify.models import PgStat
from utils.attrdict import AttrDict
from utils.db import dictfetchone, find_app_by_table


class Command(BaseCommand):
    help = 'Updates the PgStat table'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('logify.update_pgstat')

    def add_arguments(self, parser):
        parser.add_argument('-n', '--limit', type=int, help='number of tables')
        parser.add_argument('-f', '--search', type=str, help='search tables')
        parser.add_argument('--reset', action='store_true', help='reset initial_table_size')

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
                tuple_stats = dictfetchone(cursor)

                fields = [
                    'pg_total_relation_size(relid) AS table_size',
                    'pg_size_pretty(pg_total_relation_size(relid)) AS pretty_table_size',
                    '''
                    CASE
                        WHEN initial_table_size IS NULL THEN 0
                        ELSE pg_total_relation_size(relid) - initial_table_size
                    END AS diff_size
                    ''',
                    '''
                    CASE
                        WHEN initial_table_size IS NULL THEN '0'
                        ELSE pg_size_pretty(pg_total_relation_size(relid) - initial_table_size)
                    END AS pretty_diff_size
                    ''',
                    'pg_stat_user_tables.last_vacuum',
                    'pg_stat_user_tables.last_autovacuum',
                    'pg_stat_user_tables.last_analyze',
                    'pg_stat_user_tables.last_autoanalyze',
                ]
                cursor.execute(f'''
                    SELECT {', '.join(fields)}
                    FROM pg_stat_user_tables
                    LEFT JOIN logify_pgstat ON logify_pgstat.table_name = '{table}'
                    WHERE relname = '{table}'
                ''')
                table_stats = dictfetchone(cursor)

                defaults = {'app_name': find_app_by_table(table), **tuple_stats, **table_stats}

                pg_stat, created = PgStat.objects.update_or_create(table_name=table, defaults=defaults)
                if pg_stat.initial_table_size is None or args.reset:
                    pg_stat.initial_table_size = pg_stat.table_size
                    pg_stat.diff_size = 0
                    pg_stat.pretty_diff_size = '0'
                    pg_stat.save(update_fields=['initial_table_size'])
