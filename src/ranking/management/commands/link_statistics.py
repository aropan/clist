import logging
import re
from collections import defaultdict
from copy import deepcopy

import tqdm
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from clist.models import Contest, Resource
from ranking.models import Account, Statistics
from utils.attrdict import AttrDict
from utils.strings import slug_string_iou, slugify, string_iou
from utils.timetools import parse_duration


class Command(BaseCommand):
    help = 'Link statistics'

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-c', '--contest-id', type=int, help='contest id')
        parser.add_argument('-d', '--timing-delay', help='delay to update')
        parser.add_argument('-l', '--limit', type=int, help='limit contests')
        parser.add_argument('--dryrun', action='store_true', default=False)
        self.logger = logging.getLogger('ranking.parse.link_statistics')

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        now = timezone.now()

        resources = Resource.available_for_update_objects.all()
        if args.resources:
            resources = Resource.get(args.resources, queryset=resources)
        contests = Contest.objects.filter(resource__in=resources).prefetch_related('resource')
        contests = contests.filter(end_time__lt=now)
        contests = contests.filter(related_set__isnull=False)
        if args.contest_id:
            contests = contests.filter(id=args.contest_id)
        if args.timing_delay:
            timing_delay = parse_duration(args.timing_delay)
            contests = contests.filter(Q(link_statistic_timing__lt=now - timing_delay) |
                                       Q(link_statistic_timing__isnull=True))
        contests = contests.order_by('-end_time')
        if args.limit:
            contests = contests[:args.limit]

        def normalize_name(name):
            if not name:
                return name
            name = slugify(name)
            if name.startswith('the-'):
                name = name[4:]
            name = re.sub(r'\bbelarus\b', 'belarusian', name)
            return name

        @transaction.atomic
        def link_contest(contest):
            counters = defaultdict(int)
            resource = contest.resource
            account_type = Account.get_type('university')  # FIXME parameters
            related_stats = Statistics.objects.filter(contest__related=contest)
            related_stats = related_stats.filter(account__account_type=account_type)
            related_stats = related_stats.select_related('account')
            mapping_stats = defaultdict(list)
            for related_stat in related_stats:
                if related_stat.place_as_int:
                    mapping_stats[related_stat.place_as_int].append(related_stat)
                if name := normalize_name(related_stat.account.name):
                    mapping_stats[name].append(related_stat)

            def is_same_statistics(stat, related_stat, iou_stats) -> bool:
                pairs_names = [
                    (stat.addition.get('name'), related_stat.addition.get('name')),
                    (stat.account.name, related_stat.account.name),
                ]
                max_iou = 0
                for lsh, rhs in pairs_names:
                    max_iou = max(max_iou, string_iou(lsh, rhs), slug_string_iou(lsh, rhs))
                    if max_iou > 0.93:
                        return True
                pairs_names += [(n2, n1) for n1, n2 in pairs_names]
                for lsh, rhs in pairs_names:
                    if not lsh or not rhs:
                        continue
                    lsh, rhs = normalize_name(lsh), normalize_name(rhs)
                    if lsh.startswith(rhs) or lsh.endswith(rhs):
                        return True
                iou_stats.append((max_iou, related_stat))
                return False

            def update_fields(stat, related_stat):
                fields = ['country', 'team_id']  # parameters
                stat_updated = False
                for field in fields:
                    stat_value = stat.addition.get(field)
                    related_value = related_stat.addition.get(field)
                    if stat_value and related_value and stat_value != related_value:
                        self.logger.warning(f"Conflict {field}: {stat_value} != {related_value}")
                        continue
                    if not stat_value and related_value:
                        stat.addition[field] = related_value
                        stat_updated = True
                        updated_fields.add(field)
                        counters.setdefault('updated_fields', defaultdict(int))[field] += 1
                return stat_updated

            def get_related_account(related_stat):
                related_account = related_stat.account
                fields = ['name', 'country', 'account_type']
                defaults = {k: getattr(related_account, k) for k in fields}
                defaults['related'] = related_account
                account, created = Account.objects.update_or_create(resource=resource, key=related_account.key,
                                                                    defaults=defaults)
                if created:
                    counters['related_accounts_created'] += 1
                return account

            contest_stats = contest.statistics_set.all()
            contest_stats = contest_stats.exclude(account__account_type=account_type)
            contest_stats = contest_stats.filter(place_as_int__isnull=False)
            contest_stats = contest_stats.select_related('account')
            updated_fields = set()
            failed = False
            for stat in tqdm.tqdm(contest_stats.iterator(), desc=f"statistics {contest}"):
                mapping_keys = [stat.place_as_int]
                if name := normalize_name(stat.addition.get('name')):
                    mapping_keys.append(name)
                if name := normalize_name(stat.account.name):
                    mapping_keys.append(name)
                mapping_keys.extend([stat.place_as_int + 1, stat.place_as_int - 1])
                mapped_related_stats = []
                for mapping_key in mapping_keys:
                    mapped_related_stats.extend(mapping_stats.get(mapping_key, []))
                processed_related_stats = set()
                iou_stats = []
                for related_stat in mapped_related_stats:
                    if related_stat.id not in processed_related_stats:
                        processed_related_stats.add(related_stat.id)
                        if is_same_statistics(stat, related_stat, iou_stats):
                            break
                else:
                    max_iou, related_stat = max(iou_stats)
                    ok = (stat.place_as_int == related_stat.place_as_int and
                          len(mapping_stats[stat.place_as_int]) == 1)
                    if not ok:
                        failed = True
                        self.logger.warning(f"Cannot find related statistic for {stat} #{stat.place_as_int}"
                                            f", mapping keys = {mapping_keys}, max iou = {max_iou}")
                        continue

                stat_updated = update_fields(stat, related_stat)
                stat_related_account = get_related_account(related_stat)

                new_stat = Statistics.objects.filter(contest=contest, account=stat_related_account).first()
                if not new_stat:
                    new_stat = deepcopy(stat)
                    new_stat.pk = None
                    new_stat.account = stat_related_account
                    new_stat.save()
                if new_stat.related != stat:
                    new_stat.related = stat
                    new_stat.save(update_fields=['related'])

                if stat_updated:
                    stat.save(update_fields=['addition'])

                if (count := stat.related_statistics.count()) != 1:
                    failed = True
                    self.logger.warning(f"Statistic {stat} has {count} related statistics instead of 1")

            if failed:
                raise Exception(f"Failed to link statistics for contest {contest}")

            contest_fields = contest.info.setdefault("fields", [])
            hidden_fields = contest.info.setdefault("hidden_fields", [])
            contest_update_fields = {'link_statistic_timing'}
            for field in updated_fields:
                if field in contest_fields or field in hidden_fields:
                    continue
                contest_fields.append(field)
                hidden_fields.append(field)
                contest_update_fields.add('info')
            contest.link_statistic_timing = now
            contest.save(update_fields=contest_update_fields)
            self.logger.info(f"Counters: {dict(counters)}")
            self.logger.info(f"Contest {contest} done")

        for contest in tqdm.tqdm(contests, desc="contests"):
            link_contest(contest)