#!/usr/bin/env python

from collections import defaultdict
from logging import getLogger

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Prefetch, Q, Sum
from django.utils import timezone
from prettytable import PrettyTable
from sql_util.utils import Exists, SubqueryCount
from tqdm import tqdm

from clist.models import Resource
from clist.templatetags.extras import get_item, medal_as_n_medal_fields, place_as_n_place_field
from clist.utils import update_accounts_by_coders
from ranking.models import Account
from utils.attrdict import AttrDict
from utils.mathutils import is_close

ACCOUNT_MEDAL_FIELDS = ("n_win", "n_gold", "n_silver", "n_bronze", "n_medals", "n_other_medals")
CUSTOM_MEDAL_FIELDS = ("n_gold", "n_silver", "n_bronze", "n_other_medals")


def get_resource_medal_fields(resource):
    config = resource.accounts_fields.get("medal_fields", {})
    if not isinstance(config, dict):
        raise ValueError(f"{resource.host} accounts_fields.medal_fields must be a mapping")

    ret = {}
    for account_type_name, fields in config.items():
        account_type = Account.get_type(account_type_name)
        if account_type is None:
            raise ValueError(f"{resource.host} has unknown medal account type: {account_type_name}")
        if not isinstance(fields, dict):
            raise ValueError(f"{resource.host} medal fields for {account_type_name} must be a mapping")
        if not fields:
            raise ValueError(f"{resource.host} medal fields for {account_type_name} must not be empty")

        ret[account_type] = {}
        for account_field, addition_field in fields.items():
            if account_field not in CUSTOM_MEDAL_FIELDS:
                raise ValueError(f"{resource.host} has unsupported medal account field: {account_field}")
            if not isinstance(addition_field, str) or not addition_field:
                raise ValueError(f"{resource.host} addition field for {account_field} must be a non-empty string")
            ret[account_type][account_field] = addition_field
    return ret


def get_statistic_medal_stats(statistic, custom_medal_fields):
    ret = defaultdict(int)
    has_medal = False

    if statistic.medal:
        for field in medal_as_n_medal_fields(medal=statistic.medal):
            ret[field] += 1
        has_medal = True

    for account_field, addition_field in custom_medal_fields.items():
        value = get_item(statistic.addition, addition_field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
            raise ValueError(
                f"Statistic#{statistic.pk} addition.{addition_field} must be a non-negative integer, got {value!r}"
            )
        value = int(value)
        if not value:
            continue
        ret[account_field] += value
        if account_field != "n_other_medals":
            ret["n_medals"] += value
        has_medal = True

    if has_medal and statistic.place_as_int == 1:
        ret["n_win"] += 1
    return ret


class Command(BaseCommand):
    help = "Set resources accounts"

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.logger = getLogger("clist.set_resources_accounts")

    def add_arguments(self, parser):
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="*", help="host name for update")
        parser.add_argument("--orderby", help="sort resources by field")
        parser.add_argument("--limit", type=int, help="limit resources")
        parser.add_argument("--sortby", default="n_changes", help="sort table by field")
        parser.add_argument("--with-coders", action="store_true", help="update only coders")
        parser.add_argument("--with-list-values", action="store_true", help="update only list values")
        parser.add_argument("--skip-fix", action="store_true", help="skip_in_stats fix")
        parser.add_argument("--remove-empty", action="store_true", help="remove empty accounts")
        parser.add_argument("--update-statistic-stats", action="store_true", help="update statistic stats")
        parser.add_argument("--update-account-urls", action="store_true", help="update account urls")
        parser.add_argument("--with-priority", action="store_true", help="update resources by Activity score")

    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.with_priority or args.resources:
            resources = Resource.priority_objects.all()
        else:
            resources = Resource.available_for_update_objects.all()
        if args.resources:
            resources = Resource.get(args.resources, queryset=resources)
        else:
            resources = resources.filter(n_accounts__gt=0)
        if args.orderby:
            resources = resources.order_by(args.orderby)
        if args.limit:
            limit = args.limit if args.limit > 0 else resources.count() + args.limit
            resources = resources[:limit]
        self.logger.info(f"resources [{len(resources)}] = {[r.host for r in resources]}")

        with tqdm(total=len(resources), desc="resources") as pbar_resource:
            resources_data = []
            for resource in resources:
                start_time = timezone.now()

                if args.update_statistic_stats:
                    only_fields = [
                        "id",
                        "account_id",
                        "resource_id",
                        "contest_id",
                        "addition",
                        "last_activity",
                        "skip_in_stats",
                        "solving",
                        "upsolving",
                        "total_solving",
                        "n_solved",
                        "n_upsolved",
                        "n_total_solved",
                        "n_first_ac",
                        "medal",
                        "place_as_int",
                        "contest__kind",
                        "contest__is_rated",
                    ]
                    for statistic in resource.statistics_set.select_related("contest").only(*only_fields):
                        statistic.update_stats()

                    for has_field, field, field_suffix, comparable_value in (
                        ("has_statistic_total_solving", "total_solving", "__gt", 0),
                        ("has_statistic_n_first_ac", "n_first_ac", "__gt", 0),
                        ("has_statistic_n_total_solved", "n_total_solved", "__gt", 0),
                        ("has_statistic_medal", "medal", "__isnull", False),
                        ("has_statistic_place", "place_as_int", "__isnull", False),
                    ):
                        if getattr(resource, has_field) is not None:
                            continue
                        if not resource.statistics_set.filter(**{f"{field}{field_suffix}": comparable_value}).exists():
                            continue
                        setattr(resource, has_field, True)
                        resource.save(update_fields=[has_field])

                accounts = resource.account_set.all()
                if args.with_coders:
                    accounts = accounts.filter(coders__isnull=False)
                if args.with_list_values:
                    accounts = accounts.filter(listvalue__isnull=False)
                total_accounts = accounts.count()

                if args.skip_fix:
                    for value in (False, True):
                        for a in tqdm(accounts, desc="fixing skip_in_stats"):
                            qs = a.statistics_set.filter(skip_in_stats=value, addition___no_update_n_contests=not value)
                            qs.update(skip_in_stats=not value)

                counters = defaultdict(int)
                statistic_filter = Q(skip_in_stats=False, contest__stage__isnull=True, contest__invisible=False)
                medal_fields = get_resource_medal_fields(resource)

                def set_n_field(count_annotation, count_field, accounts=accounts, counters=counters):
                    qs = accounts.annotate(count=count_annotation).exclude(**{count_field: F("count")})
                    qs = qs.only("resource_id", count_field)
                    counter = 0
                    with tqdm(desc=f"updating {count_field}") as pbar:
                        for a in qs:
                            value = getattr(a, count_field)
                            if not is_close(value, a.count):
                                counter += 1
                                setattr(a, count_field, a.count)
                                a.save(update_fields=[count_field])
                            pbar.update()
                        pbar.close()
                    self.logger.info(f"updated {count_field} = {counter}")
                    counters[count_field] = counter

                def set_n_medal_field(resource, accounts, counters, medal_fields):
                    medal_filter = Q(medal__isnull=False)
                    for account_type, fields in medal_fields.items():
                        custom_medal_filter = Q()
                        for addition_field in fields.values():
                            lookup = addition_field.replace(".", "__")
                            custom_medal_filter |= Q(**{f"addition__{lookup}__isnull": False})
                        medal_filter |= Q(account__account_type=account_type) & custom_medal_filter

                    statistics_with_medals = resource.statistics_set.filter(medal_filter)
                    qs = accounts.prefetch_related(Prefetch("statistics_set", queryset=statistics_with_medals))
                    qs = qs.annotate(count=SubqueryCount("statistics", filter=medal_filter))
                    has_stored_medals = Q()
                    for field in ACCOUNT_MEDAL_FIELDS:
                        has_stored_medals |= Q(**{f"{field}__isnull": False})
                    qs = qs.filter(Q(count__gt=0) | has_stored_medals)
                    counter = 0
                    with tqdm(desc="updating n_medals") as pbar:
                        for a in qs:
                            medal_stats = defaultdict(int)
                            custom_medal_fields = medal_fields.get(a.account_type, {})
                            for s in a.statistics_set.all():
                                for field, value in get_statistic_medal_stats(s, custom_medal_fields).items():
                                    medal_stats[field] += value
                            updated_fields = []
                            for field in ACCOUNT_MEDAL_FIELDS:
                                value = medal_stats.get(field)
                                if not is_close(value, getattr(a, field)):
                                    setattr(a, field, value)
                                    updated_fields.append(field)
                            if updated_fields:
                                counter += 1
                                a.save(update_fields=updated_fields)
                            pbar.update()
                    self.logger.info(f"updated n_medals = {counter}")
                    counters["n_medals"] = counter

                def set_n_place_field(
                    statistic_filter=statistic_filter, resource=resource, accounts=accounts, counters=counters
                ):
                    place_filter = Q(place_as_int__gte=1, place_as_int__lte=10, contest__end_time__lt=timezone.now())
                    place_filter = place_filter & statistic_filter
                    statistics_with_places = resource.statistics_set.filter(place_filter)
                    qs = accounts.prefetch_related(Prefetch("statistics_set", queryset=statistics_with_places))
                    qs = qs.annotate(count=SubqueryCount("statistics", filter=place_filter))
                    qs = qs.filter(Q(count__gt=0) | Q(n_places__isnull=False))
                    counter = 0
                    with tqdm(desc="updating n_places") as pbar:
                        for a in qs:
                            place_stats = defaultdict(int)
                            for s in a.statistics_set.all():
                                n_place_field = place_as_n_place_field(s.place_as_int)
                                place_stats[n_place_field] += 1
                                place_stats["n_places"] += 1
                            updated_fields = []
                            for field in [
                                "n_first_places",
                                "n_second_places",
                                "n_third_places",
                                "n_top_ten_places",
                                "n_places",
                            ]:
                                value = place_stats.get(field)
                                if not is_close(value, getattr(a, field)):
                                    setattr(a, field, value)
                                    updated_fields.append(field)
                            if updated_fields:
                                counter += 1
                                a.save(update_fields=updated_fields)
                            pbar.update()
                    self.logger.info(f"updated n_places = {counter}")
                    counters["n_places"] = counter

                def set_sum_field(sum_annotations, annotation_filter, name, accounts=accounts, counters=counters):
                    fields = list(sum_annotations.keys())
                    qs = accounts
                    qs = qs.filter(annotation_filter)
                    for field, annotation in sum_annotations.items():
                        qs = qs.annotate(**{f"_{field}": Sum(annotation)})
                    qs = qs.only("resource_id", *fields)
                    counter = 0
                    with tqdm(desc=f"updating {name}") as pbar:
                        for a in qs:
                            updated_fields = []
                            for field in fields:
                                value = getattr(a, f"_{field}") or 0
                                if not is_close(value, getattr(a, field)):
                                    setattr(a, field, value)
                                    updated_fields.append(field)
                            if updated_fields:
                                counter += 1
                                a.save(update_fields=updated_fields)
                            pbar.update()
                    self.logger.info(f"updated {name} = {counter}")
                    counters[name] = counter

                def set_account_url(accounts, counters=counters):
                    with tqdm(total=accounts.count(), desc="updating account urls") as pbar:
                        counters["n_urls"] = update_accounts_by_coders(accounts, progress_bar=pbar)

                set_n_field(SubqueryCount("statistics", filter=statistic_filter), "n_contests")
                set_n_field(SubqueryCount("writer_set"), "n_writers")
                set_n_field(SubqueryCount("subscribers"), "n_subscribers")
                set_n_field(SubqueryCount("listvalue"), "n_listvalues")

                if (
                    resource.has_statistic_total_solving
                    or resource.has_statistic_n_first_ac
                    or resource.has_statistic_n_total_solved
                ):
                    statistic_fields_annotation = {
                        field: f"statistics__{field}" for field in ["solving", *settings.STANDINGS_STATISTIC_FIELDS]
                    }
                    set_sum_field(
                        statistic_fields_annotation,
                        annotation_filter=Q(statistics__contest__in=resource.major_contests()),
                        name="n_stats",
                    )

                if resource.has_statistic_medal or medal_fields:
                    set_n_medal_field(resource, accounts, counters, medal_fields)

                if resource.has_statistic_place is not False:
                    set_n_place_field()
                    resource.has_statistic_place = True
                    resource.save(update_fields=["has_statistic_place"])

                if args.remove_empty:
                    qs = accounts.annotate(
                        has_coders=Exists("coders"),
                        has_statistics=Exists("statistics"),
                        has_writers=Exists("writer_set"),
                    ).filter(
                        has_coders=False,
                        has_statistics=False,
                        has_writers=False,
                    )
                    counters["n_removed"], _ = qs.delete()

                if args.update_account_urls:
                    set_account_url(accounts)

                n_changes = sum(counters.values())

                delta_time = timezone.now() - start_time
                pbar_resource.set_postfix(
                    resource=resource.host,
                    time=delta_time,
                    total=total_accounts,
                    n_changes=n_changes,
                )
                pbar_resource.update()

                resource_data = {
                    "host": resource.host,
                    "time": delta_time,
                    "n_accounts": total_accounts,
                    "n_changes": n_changes,
                    **counters,
                }
                resources_data.append(resource_data)
            pbar_resource.close()

            fields = []
            for resource_data in resources_data:
                for field in resource_data:
                    if field not in fields:
                        fields.append(field)

            table = PrettyTable(field_names=fields, sortby=args.sortby)
            for resource_data in resources_data:
                table.add_row([resource_data.get(field, "") for field in fields])
            print(table)
