import html
import logging
import re
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import tqdm
from django.core.management.base import BaseCommand

from clist.models import Contest, Resource
from ranking.management.modules.common import REQ
from ranking.models import Account, Finalist
from utils.attrdict import AttrDict
from utils.parsed_table import ParsedTable


class Command(BaseCommand):
    help = 'Parse finalists'

    def add_arguments(self, parser):
        parser.add_argument('--contest', type=int, help='contest id', required=True)
        parser.add_argument('--resource', help='resource name of finalists', required=True)
        parser.add_argument('--url', help='url to parse table with finalists', required=True)
        parser.add_argument('--member-field', help='field for member', required=True)
        parser.add_argument('--name-field', help='field for name')
        parser.add_argument('--member-from-url', help='regex to extract member from url')
        parser.add_argument('--filter-field', help='field name to filter rows')
        parser.add_argument('--filter-value', help='regex to filter rows by filter field')
        parser.add_argument('--cphof-url-field', help='field for CPHOF url')
        parser.add_argument('--resource-fields', nargs='+', help='resource fields')
        parser.add_argument('--dryrun', action='store_true', help='dry run without making changes')
        self.logger = logging.getLogger('ranking.parse.finalists')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        contest = Contest.get(args.contest)
        resource = Resource.get(args.resource)
        resources = [Resource.get(r) for r in args.resource_fields] if args.resource_fields else []

        page = REQ.get(args.url)
        tables = re.finditer(r'<table[^>]*>.*?</table>', page, re.DOTALL)
        counters = defaultdict(int)
        missed_accounts = set()
        missed_coders = set()
        fields = []
        for table in tables:
            table = ParsedTable(table.group(), as_list=True)
            if args.name_field and not any(re.search(args.name_field, col.value) for col in table.header.columns):
                continue
            if not any(re.search(args.member_field, col.value) for col in table.header.columns):
                continue

            for row in tqdm.tqdm(table, desc='table rows'):
                names = []
                members = []
                info = {}
                row_data = []
                cphof_url = None
                cphof_resource = None
                for field, cell in row:
                    row_data.append((field, cell.value))
                    if args.cphof_url_field and re.search(args.cphof_url_field, field):
                        if not cphof_resource:
                            cphof_resource = Resource.get('cphof')
                        for href in cell.column.node.xpath('.//a/@href'):
                            url = urljoin(args.url, href)
                            domain = urlparse(url).netloc
                            if domain == cphof_resource.host:
                                if cphof_url:
                                    self.logger.warning(f'Multiple cphof urls in {row_data}')
                                    continue
                                cphof_url = url
                    if args.name_field and re.search(args.name_field, field):
                        names.append(cell.value)
                        continue
                    if re.search(args.member_field, field):
                        member = cell.value
                        if args.member_from_url:
                            for href in cell.column.node.xpath('.//a/@href'):
                                if re.search(args.member_from_url, href):
                                    member = href.rstrip('/').split('/')[-1]
                                    break
                        members.append(member)
                        continue
                    info[field] = cell.value
                    if field not in fields:
                        fields.append(field)

                if args.name_field and not names:
                    self.logger.warning(f'No name field in {row_data}')
                    continue
                if len(names) > 1:
                    self.logger.warning(f'Multiple name fields in {row_data}')
                    continue
                if not args.name_field and len(members) != 1:
                    self.logger.warning(f'Without name field not exactly one member field in {row_data}')
                    continue
                if args.filter_field:
                    if not args.filter_value:
                        self.logger.warning('Filter field specified without filter value')
                        continue
                    if not re.search(args.filter_value, info[args.filter_field]):
                        self.logger.warning(f'Filtered out for {row_data}')
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
                    self.logger.info(f'Would process: {names=}, {members=}, {accounts=}, {info=}')
                    continue

                if args.cphof_url_field:
                    if not cphof_url:
                        self.logger.warning(f'cphof url field specified but not found in {row_data}')
                        continue
                    if not accounts:
                        self.logger.warning(f'cphof url specified but no accounts found in {row_data}')
                        continue
                    page = REQ.get(cphof_url)
                    match = re.search('<link[^>]*rel="canonical"[^>]*href="[^"]*/profile/(?P<handle>[^"]*)"[^>]*>', page)
                    handle = html.unescape(match.group('handle'))
                    cphof_account = cphof_resource.account_set.filter(key=handle).first()
                    if not cphof_account:
                        self.logger.warning(f'cphof account not found for handle "{handle}" from url "{cphof_url}"')
                    else:
                        cphof_coder = cphof_account.coders.first()
                        for account in accounts:
                            account.coders.add(cphof_coder)

                name = names[0] if args.name_field else members[0]
                finalist, created = Finalist.objects.get_or_create(contest_id=args.contest, name=name)
                created_name = 'created' if created else 'already_created'
                counters[created_name] += 1

                finalist.accounts.set(accounts)
                finalist.info.update(info)
                finalist.save()

        finalists_info = {
            'parse_args': args,
            'n_finalists': contest.finalist_set.count(),
            'resource': resource.pk,
            'fields': fields,
            'resources': [resource.pk for resource in resources],
            'has_name': bool(args.name_field),
        }
        if args.dryrun:
            self.logger.info(f'Dry run, no changes made, {finalists_info=}')
            return

        contest.finalists_info = finalists_info
        contest.save(update_fields=['finalists_info'])

        if counters:
            self.logger.info(f'counters = {dict(counters)}')
        if missed_accounts:
            self.logger.warning(f'missed {len(missed_accounts)} accounts = {missed_accounts}')
        if missed_coders:
            self.logger.warning(f'missed {len(missed_coders)} coders = {missed_coders}')
