#!/usr/bin/env python
# -*- coding: utf-8 -*-

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django_print_sql import print_sql_decorator

from clist.models import Resource
from pyclist.decorators import analyze_db_queries
from ranking.models import Account
from utils.attrdict import AttrDict
from utils.strings import generate_secret_64


class Command(BaseCommand):
    help = "Anonymize accounts"

    def __init__(self, *args, **kw):
        super(Command, self).__init__(*args, **kw)
        self.logger = getLogger("ranking.anonymize.account")

    def add_arguments(self, parser):
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="*", help="host name for update")
        parser.add_argument("-q", "--query", required=True, nargs="+", help="account key or name")
        parser.add_argument("-rq", "--regex-query", action="store_true", help="regex for account key or name")
        parser.add_argument("-n", "--dryrun", action="store_true", help="do not save changes to db")
        parser.add_argument("--name", default="anonymized", help="new name for account")

    @print_sql_decorator(count_only=True)
    @analyze_db_queries()
    @transaction.atomic()
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        accounts = Account.objects.all()

        condition = Q()
        query_suffix = "__regex" if args.regex_query else ""
        for query in args.query:
            for field in ("key", "name"):
                field_name = f"{field}{query_suffix}"
                condition |= Q(**{field_name: query})
        accounts = accounts.filter(condition)

        if args.resources:
            resources = Resource.get(args.resources)
            accounts = accounts.filter(resource__in=resources)

        self.logger.info(f"Found {accounts.count()} accounts to anonymize")

        for account in accounts:
            new_key = generate_secret_64()
            new_name = args.name
            self.logger.info(f"Anonymizing account {account.key} ({account.name}) -> {new_key} ({new_name})")
            if args.dryrun:
                continue
            for statistic in account.statistics_set.select_related("contest"):
                contest = statistic.contest
                additions = contest.info.setdefault("additions", {})
                addition = additions.setdefault(account.key, {})
                addition["member"] = new_key
                addition["name"] = new_name
                addition["__update_only"] = True
                contest.save(update_fields=["info"])

                addition = statistic.addition
                if "name" in addition and addition["name"] != new_name:
                    addition["name"] = new_name
                    statistic.save(update_fields=["addition"])

            account.name = new_name
            account.key = new_key
            account.url = account.account_default_url()
            account.save(update_fields=["name", "key", "url"])
