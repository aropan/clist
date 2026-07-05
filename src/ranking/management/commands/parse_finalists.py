import html
import logging
import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import tqdm
from django.core.management.base import BaseCommand
from django.db.models import Q, OuterRef
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.management.modules.common import REQ
from ranking.models import Account, Finalist, FinalistResourceInfo, Statistics
from utils.attrdict import AttrDict
from utils.parsed_table import ParsedTable
from utils.rating import get_rating
from clist.templatetags.extras import get_item
from sql_util.utils import Exists


class Command(BaseCommand):
    help = "Parse finalists"

    def add_arguments(self, parser):
        parser.add_argument("--contest", type=int, help="contest id", required=True)
        parser.add_argument("--resource", help="resource name of finalists")
        parser.add_argument("--from-handles", nargs="*", help="handles of finalists")
        parser.add_argument("--from-url", help="url to parse table with finalists")
        parser.add_argument("--from-info", action="store_true", help="get args from contest finalists info")
        parser.add_argument("--from-contest", type=int, help="contest id")
        parser.add_argument("--member-field", help="field for member")
        parser.add_argument("--name-field", help="field for name")
        parser.add_argument("--member-from-url", help="regex to extract member from url")
        parser.add_argument("--filter-field", help="field name to filter rows")
        parser.add_argument("--filter-value", help="regex to filter rows by filter field")
        parser.add_argument("--cphof-url-field", help="field for CPHOF url")
        parser.add_argument("--resource-fields", nargs="+", help="resource fields")
        parser.add_argument("--additional-fields", nargs="*", help="additional fields")
        parser.add_argument("--order-by-fields", nargs="*", help="order-by fields")
        parser.add_argument("--dryrun", action="store_true", help="dry run without making changes")
        self.logger = logging.getLogger("ranking.parse.finalists")

    def handle(self, *args, **options):
        args = AttrDict(options)
        contest = Contest.get(args.contest)
        if args.from_info:
            args.update(AttrDict(contest.finalists_info["parse_args"]))
        self.stdout.write(str(args))

        resource = Resource.get(args.resource)
        resources = [Resource.get(r) for r in args.resource_fields] if args.resource_fields else []

        counters = defaultdict(int)
        missed_accounts = set()
        missed_coders = set()
        cphof_resource = None

        def get_finalists_from_url():
            nonlocal cphof_resource
            page = REQ.get(args.from_url)
            tables = re.finditer(r"<table[^>]*>.*?</table>", page, re.DOTALL)
            fields = []
            ret = []
            for table in tables:
                table = ParsedTable(table.group(), as_list=True)
                if args.name_field and not any(re.search(args.name_field, col.value) for col in table.header.columns):
                    continue
                if not any(re.search(args.member_field, col.value) for col in table.header.columns):
                    continue

                for row in tqdm.tqdm(table, desc="table rows"):
                    names = []
                    members = []
                    info = {}
                    row_data = []
                    cphof_url = None
                    for field, cell in row:
                        row_data.append((field, cell.value))
                        if args.cphof_url_field and re.search(args.cphof_url_field, field):
                            if not cphof_resource:
                                cphof_resource = Resource.get("cphof")
                            for href in cell.column.node.xpath(".//a/@href"):
                                url = urljoin(args.from_url, href)
                                domain = urlparse(url).netloc
                                if domain == cphof_resource.host:
                                    if cphof_url:
                                        self.logger.warning(f"Multiple cphof urls in {row_data}")
                                        continue
                                    cphof_url = url
                        if args.name_field and re.search(args.name_field, field):
                            names.append(cell.value)
                            continue
                        if re.search(args.member_field, field):
                            member = cell.value
                            if args.member_from_url:
                                for href in cell.column.node.xpath(".//a/@href"):
                                    if re.search(args.member_from_url, href):
                                        member = href.rstrip("/").split("/")[-1]
                                        break
                            members.append(member)
                            continue
                        info[field] = cell.value
                        if field not in fields:
                            fields.append(field)

                    if args.name_field and not names:
                        self.logger.warning(f"No name field in {row_data}")
                        continue
                    if len(names) > 1:
                        self.logger.warning(f"Multiple name fields in {row_data}")
                        continue
                    if not args.name_field and len(members) != 1:
                        self.logger.warning(f"Without name field not exactly one member field in {row_data}")
                        continue
                    if args.filter_field:
                        if not args.filter_value:
                            self.logger.warning("Filter field specified without filter value")
                            continue
                        if not re.search(args.filter_value, info[args.filter_field]):
                            self.logger.warning(f"Filtered out for {row_data}")
                            continue

                    accounts = []
                    for member in members:
                        if member in missed_accounts or (account := Account.get(resource, member)) is None:
                            missed_accounts.add(member)
                            self.logger.warning(f'Account "{member}" not found')
                            continue
                        if not account.coders.all():
                            missed_coders.add(account)
                        accounts.append(account)

                    if args.dryrun:
                        self.logger.info(f"Would process: {names=}, {members=}, {accounts=}, {info=}")
                        continue

                    name = names[0] if args.name_field else members[0]
                    ret.append({"name": name, "accounts": accounts, "cphof_url": cphof_url, "info": info})

            return ret, fields

        def get_finalists_from_data(handles):
            ret = []
            accounts = Account.objects.filter(resource=resource, key__in=handles).prefetch_related("coders")
            accounts = {account.key: account for account in accounts}
            fields = args.additional_fields or []
            for handle in handles:
                account = accounts.get(handle) or Account.get(resource, handle)
                if not account:
                    self.logger.warning(f'Account "{handle}" not found')
                    continue
                info = {field: account.info[field] for field in fields if field in account.info}
                ret.append({"name": handle, "accounts": [account], "info": info})
            return ret, fields

        def get_finalists_from_contest(contest_id):
            contest = Contest.get(contest_id)
            ret = []
            fields = args.additional_fields or []
            for statistic in contest.statistics_set.prefetch_related("contest__resource", "account").filter(
                advanced=True
            ):
                info = {}
                for field in fields:
                    if value := get_item(statistic, field):
                        info[field] = value
                ret.append({"name": statistic.account_name, "accounts": [statistic.account], "info": info})
            return ret, fields

        if args.from_handles:
            finalists, fields = get_finalists_from_data(args.from_handles)
        elif args.from_url:
            finalists, fields = get_finalists_from_url()
        elif args.from_contest:
            finalists, fields = get_finalists_from_contest(args.from_contest)
        else:
            self.logger.error("No handles or url specified")
            return

        max_accounts_size = 0
        has_country = False
        for finalist_info in tqdm.tqdm(finalists):
            accounts = finalist_info["accounts"]
            if args.cphof_url_field:
                cphof_url = finalist_info.get("cphof_url")
                if not cphof_url:
                    self.logger.warning("cphof url field specified but not found")
                    continue
                if not accounts:
                    self.logger.warning("cphof url specified but no accounts found")
                    continue
                page = REQ.get(cphof_url)
                match = re.search('<link[^>]*rel="canonical"[^>]*href="[^"]*/profile/(?P<handle>[^"]*)"[^>]*>', page)
                handle = html.unescape(match.group("handle"))
                cphof_account = cphof_resource.account_set.filter(key=handle).first()
                if not cphof_account:
                    self.logger.warning(f'cphof account not found for handle "{handle}" from url "{cphof_url}"')
                else:
                    cphof_coder = cphof_account.coders.first()
                    for account in accounts:
                        account.coders.add(cphof_coder)

            finalist, created = Finalist.objects.get_or_create(contest_id=args.contest, name=finalist_info["name"])
            created_name = "created" if created else "already_created"
            counters[created_name] += 1

            finalist_accounts = set() if args.from_contest else set(accounts)
            finalist.info.update(finalist_info["info"])
            finalist.save()

            coders = [coder for account in accounts for coder in account.coders.all()]
            # last_modified = max(a.modified for a in accounts)
            for resource_id, resource_ in enumerate(resources):
                accounts_filter = Q(pk__in={account.pk for account in accounts})
                coders_filter = Q(coders__in=coders)
                rating_accounts = resource_.account_set.filter(rating__isnull=False)
                rating_accounts = rating_accounts.filter(accounts_filter).union(rating_accounts.filter(coders_filter))
                if args.from_contest and resource_id == 0:
                    finalist_accounts |= set(rating_accounts)
                ratings_data = rating_accounts.values("rating", "key")
                if not ratings_data:
                    continue

                rating = round(get_rating([r["rating"] for r in ratings_data]))
                if len(ratings_data) > 1:
                    rating_infos = []
                    for rating_data in ratings_data:
                        ratings = [r["rating"] for r in ratings_data if r["key"] != rating_data["key"]]
                        rating_infos.append({"delta": rating - round(get_rating(ratings)), **rating_data})
                else:
                    rating_infos = [dict(r) for r in ratings_data]

                resource_info, _ = FinalistResourceInfo.objects.get_or_create(finalist=finalist, resource=resource_)
                resource_info.ratings = rating_infos
                resource_info.rating = rating
                resource_info.updated = timezone.now()
                resource_info.save()

            max_accounts_size = max(max_accounts_size, len(finalist_accounts))
            has_country = has_country or any(account.country for account in finalist_accounts)
            finalist.accounts.set(finalist_accounts)

        finalists_info = {
            "parse_args": args,
            "n_finalists": contest.finalist_set.count(),
            "max_accounts_size": max_accounts_size,
            "has_country": has_country,
            "resource": resource.pk,
            "fields": fields,
            "resources": [resource.pk for resource in resources],
            "has_name": bool(args.name_field),
            "order_by": args.order_by_fields or [],
        }
        if args.dryrun:
            self.logger.info(f"Dry run, no changes made, {finalists_info=}")
            return

        contest.finalists_info = finalists_info
        contest.save(update_fields=["finalists_info"])

        if counters:
            self.logger.info(f"counters = {dict(counters)}")
        if missed_accounts:
            self.logger.warning(f"missed {len(missed_accounts)} accounts = {missed_accounts}")
        if missed_coders:
            self.logger.warning(f"missed {len(missed_coders)} coders = {missed_coders}")
