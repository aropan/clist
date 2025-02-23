import logging
import re
from collections import defaultdict

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
        parser.add_argument('--name-field', help='field for name')
        parser.add_argument('--member-field', help='field for member')
        parser.add_argument('--member-from-url', help='regex to extract member from url')
        self.logger = logging.getLogger('ranking.parse.finalists')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        contest = Contest.get(args.contest)
        resource = Resource.get(args.resource)

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
                for field, cell in row:
                    row_data.append((field, cell.value))
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

                accounts = []
                for member in members:
                    if member in missed_accounts or (account := Account.get(resource, member)) is None:
                        missed_accounts.add(member)
                        self.logger.warning(f'Account "{member}" not found')
                        continue
                    if not account.coders.all():
                        missed_coders.add(account)
                    accounts.append(account)
                if args.name_field:
                    finalist, created = Finalist.objects.get_or_create(contest_id=args.contest, name=names[0])
                    created_name = 'created' if created else 'already_created'
                    counters[created_name] += 1
                else:
                    raise NotImplementedError('Finalist without name field')

                finalist.accounts.set(accounts)
                finalist.info.update(info)
                finalist.save()

        contest.finalists_info = {
            'parse_args': args,
            'n_finalists': contest.finalist_set.count(),
            'fields': fields,
            'resources': [resource.pk],
            'has_name': bool(args.name_field),
        }
        contest.save(update_fields=['finalists_info'])

        if counters:
            self.logger.info(f'counters = {dict(counters)}')
        if missed_accounts:
            self.logger.warning(f'missed {len(missed_accounts)} accounts = {missed_accounts}')
        if missed_coders:
            self.logger.warning(f'missed {len(missed_coders)} coders = {missed_coders}')
