#!/usr/bin/env python3

import gzip
import json
import os
import re
import shutil
import tempfile
import traceback
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import NamedTuple

from django.conf import settings
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.db.models import BooleanField, Case, F, Value, When
from django.utils import timezone
from django_print_sql import print_sql_decorator

from clist.models import Contest, Resource
from ranking.models import Statistics
from ranking.tests.parser_regression import (
    PARSER_FIXTURES_ROOT,
    discover_parser_fixtures,
    fixture_file_path,
    fixture_path_for_contest,
    get_standings,
    normalize_standings,
    standings_context_from_statistics,
    write_expected_standings,
    write_json,
)
from utils.attrdict import AttrDict
from utils.filesystem import chown_tree_to_existing_parent_owner, is_effective_root

SENSITIVE_NAME_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|session|token|api[_-]?key|apisig)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_RE = re.compile(
    rb"""(?ix)
    (?:^|[?&{,\s])
    ["']?
    (?:access[_-]?token|refresh[_-]?token|authorization|password|secret|session[_-]?id)
    ["']?
    \s*[:=]\s*
    ["']?
    [a-z0-9/+_.=-]{8,}
    """
)

SUGGESTION_RESOURCES = (
    "codeforces.com",
    "codechef.com",
    "atcoder.jp",
    "leetcode.com",
    "luogu.com.cn",
    "ac.nowcoder.com",
    "my.newtonschool.co",
    "basecamp.eolymp.com",
    "uoj.ac",
    "codingame.com",
    "projecteuler.net",
    "ucup.ac",
    "potyczki.mimuw.edu.pl",
)
ANNUAL_SERIES = ("byio", "ioi", "icpc", "nef", "vkoshp", "fhc")


class CoverageField(NamedTuple):
    name: str
    query_name: str | None = None
    model_attribute: str | None = None
    is_null: bool = False

    @property
    def query(self):
        return self.query_name or self.name

    @property
    def attribute(self):
        return self.model_attribute or self.name


class SelectedStatistics(NamedTuple):
    statistics: list
    users: list[str]
    statistics_by_key: dict
    addition_keys: set[str]


COVERAGE_FIELDS = (
    CoverageField("kind"),
    CoverageField("standings_kind"),
    CoverageField("invisible"),
    CoverageField("is_rated"),
    CoverageField("series", query_name="series_is_null", model_attribute="series_id", is_null=True),
    CoverageField("with_medals"),
)
COVERAGE_QUERY_FIELDS = tuple(field.query for field in COVERAGE_FIELDS)


def coverage_values(fields):
    values = {}
    for field in COVERAGE_FIELDS:
        value = fields.get(field.name)
        values[field.name] = value is None if field.is_null else value
    return values


def coverage_key(resource_id, values):
    return (
        resource_id,
        *(values[field.name] for field in COVERAGE_FIELDS),
    )


def contest_coverage_values(contest):
    fields = {field.name: getattr(contest, field.attribute) for field in COVERAGE_FIELDS}
    return coverage_values(fields)


def contest_coverage_key(contest):
    return coverage_key(contest.resource_id, contest_coverage_values(contest))


def load_fixture_metadata(fixture_path):
    objects = json.loads((fixture_path / "db.json").read_text())
    resource_ids = {obj["pk"] for obj in objects if obj["model"] == "clist.resource"}
    fixture_contests = [obj for obj in objects if obj["model"] == "clist.contest"]
    if len(fixture_contests) != 1:
        raise CommandError(f"expected one clist.contest in {fixture_path / 'db.json'}")

    contest = fixture_contests[0]
    fields = contest["fields"]
    resource_id = fields["resource"]
    if resource_id not in resource_ids:
        raise CommandError(f"contest resource is missing in {fixture_path / 'db.json'}")

    return {
        "contest_id": contest["pk"],
        "fields": fields,
        "resource_id": resource_id,
    }


def load_fixture_coverage(root=PARSER_FIXTURES_ROOT):
    combinations = set()
    contests = set()

    for fixture_path in discover_parser_fixtures(root):
        metadata = load_fixture_metadata(fixture_path)
        contests.add((metadata["resource_id"], metadata["contest_id"]))
        combinations.add(coverage_key(metadata["resource_id"], coverage_values(metadata["fields"])))

    return combinations, contests


def addition_key_paths(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            path = (*prefix, str(key))
            yield ".".join(path)
            yield from addition_key_paths(item, path)
    elif isinstance(value, list):
        for item in value:
            yield from addition_key_paths(item, (*prefix, "[]"))


class Command(BaseCommand):
    help = "Record a parser fixture or suggest contests missing from fixture coverage"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger("ranking.dump_parser_fixture")
        self.verbosity = 1

    def set_verbosity(self, verbosity):
        self.verbosity = int(verbosity or 1)

    def style_enabled(self):
        return self.style.SQL_TABLE("x") != "x"

    def dim(self, message):
        return f"\033[2m{message}\033[0m" if self.style_enabled() else message

    def verbose(self, message, level=2):
        if self.verbosity >= level:
            prefix = "  • " if level <= 2 else "    · "
            line = f"{prefix}{message}"
            line = self.dim(line) if level >= 3 else self.style.SQL_FIELD(line)
            self.stdout.write(line)

    def format_error_traceback(self, error, show_locals=False):
        traceback_exception = traceback.TracebackException.from_exception(error, capture_locals=show_locals)
        return "".join(traceback_exception.format())

    def display_path(self, path):
        path = Path(path)
        return path.relative_to(Path.cwd()) if path.is_absolute() and path.is_relative_to(Path.cwd()) else path

    def describe_standings(self, standings):
        if not isinstance(standings, dict):
            return f"type={type(standings).__name__}"
        parts = [f"keys={sorted(standings)}"]
        result = standings.get("result")
        problems = standings.get("problems")
        if isinstance(result, dict):
            parts.append(f"result={len(result)}")
        if isinstance(problems, (list, tuple, dict)):
            parts.append(f"problems={len(problems)}")
        return ", ".join(parts)

    def diff_path(self, path, key):
        if isinstance(key, str) and re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            return f"{path}.{key}"
        return f"{path}[{key!r}]"

    def diff_value(self, value):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if len(value) > 200:
            value = value[:200] + "..."
        return value

    def standings_diff_lines(self, live, replayed, limit=3):
        missing = object()
        lines = []

        def add(path, message, live_value=missing, replayed_value=missing):
            line = f"{path}: {message}"
            if live_value is not missing:
                line += f"; live={self.diff_value(live_value)}"
            if replayed_value is not missing:
                line += f"; replay={self.diff_value(replayed_value)}"
            lines.append(line)

        def walk(path, live_value, replayed_value):
            if len(lines) >= limit:
                return

            if type(live_value) is not type(replayed_value):
                add(
                    path,
                    f"type differs ({type(live_value).__name__} != {type(replayed_value).__name__})",
                    live_value,
                    replayed_value,
                )
                return

            if isinstance(live_value, dict):
                live_keys = set(live_value)
                replayed_keys = set(replayed_value)
                for key in sorted(live_keys - replayed_keys, key=str):
                    if len(lines) >= limit:
                        return
                    add(self.diff_path(path, key), "missing in replay", live_value[key])
                for key in sorted(replayed_keys - live_keys, key=str):
                    if len(lines) >= limit:
                        return
                    add(self.diff_path(path, key), "extra in replay", replayed_value=replayed_value[key])
                for key in sorted(live_keys & replayed_keys, key=str):
                    walk(self.diff_path(path, key), live_value[key], replayed_value[key])
                    if len(lines) >= limit:
                        return
                return

            if isinstance(live_value, list):
                for index, (live_item, replayed_item) in enumerate(zip(live_value, replayed_value)):
                    walk(f"{path}[{index}]", live_item, replayed_item)
                    if len(lines) >= limit:
                        return
                if len(live_value) != len(replayed_value):
                    add(path, f"list length differs ({len(live_value)} != {len(replayed_value)})")
                return

            if live_value != replayed_value:
                add(path, "value differs", live_value, replayed_value)

        walk("$", live, replayed)
        return lines

    def assert_same_normalized_standings(self, live, replayed, message):
        live = normalize_standings(live)
        replayed = normalize_standings(replayed)
        if live == replayed:
            return

        short_diff = self.standings_diff_lines(live, replayed, limit=3)
        if self.verbosity >= 2:
            self.stderr.write(self.style.WARNING("Normalized standings differ:"))
            for line in self.standings_diff_lines(live, replayed, limit=20):
                self.stderr.write(self.style.WARNING(f"  - {line}"))

        detail = "; ".join(short_diff) if short_diff else "no diff details"
        raise CommandError(f"{message}: {detail}")

    def add_arguments(self, parser):
        parser.add_argument("--contest-id", type=int, help="existing contest id")
        parser.add_argument("-r", "--resource", metavar="HOST", help="resource host or short host")
        parser.add_argument("--resource-id", type=int, help="existing resource id")
        parser.add_argument("-c", "--contest-key", help="contest key within the resource")
        parser.add_argument(
            "--update",
            action="store_true",
            help=(
                "without --suggest, replay the existing HTTP cache and update db.json plus expected_standings.json; "
                "with --suggest, record every missing fixture"
            ),
        )
        parser.add_argument(
            "--suggest",
            action="store_true",
            help="list latest contests needed to cover parser variants and annual series",
        )
        parser.add_argument(
            "--force-update",
            action="store_true",
            help="with --suggest --update, record candidates even when they already have fixtures",
        )
        parser.add_argument(
            "--show-sensitive-matches",
            action="store_true",
            help="include matched secret values in fixture credential-scan errors; unsafe for shared logs",
        )
        parser.add_argument(
            "--fail-fast",
            "--stop-on-error",
            dest="fail_fast",
            action="store_true",
            help="with --suggest --update, stop recording fixtures after the first failure",
        )
        parser.add_argument(
            "--show-error-locals",
            action="store_true",
            help=(
                "include local variables in per-fixture error tracebacks; "
                "unsafe for shared logs and implies --traceback"
            ),
        )

    def get_contest(self, args):
        by_id = args.contest_id is not None
        by_key = args.resource is not None or args.resource_id is not None or args.contest_key is not None
        if by_id == by_key:
            raise CommandError("provide either --contest-id or --contest-key with --resource/--resource-id")

        queryset = Contest.objects.select_related("resource__module")
        if by_id:
            try:
                return queryset.get(pk=args.contest_id)
            except Contest.DoesNotExist as error:
                raise CommandError(f"contest id {args.contest_id} not found") from error

        if bool(args.resource) == (args.resource_id is not None):
            raise CommandError("provide exactly one of --resource or --resource-id with --contest-key")
        if not args.contest_key:
            raise CommandError("--contest-key must be used with --resource or --resource-id")

        if args.resource_id is not None:
            try:
                resource = Resource.objects.get(pk=args.resource_id)
            except Resource.DoesNotExist as error:
                raise CommandError(f"resource id {args.resource_id} not found") from error
        else:
            resource = Resource.get(args.resource, queryset=Resource.objects.all(), raise_exception=CommandError)
        try:
            return queryset.get(resource=resource, key=args.contest_key)
        except Contest.DoesNotExist as error:
            raise CommandError(f"contest {resource.host}/{args.contest_key} not found") from error

    def fixture_path_for_recording(self, contest):
        fixture_paths = []
        for fixture_path in discover_parser_fixtures():
            metadata = load_fixture_metadata(fixture_path)
            if (metadata["resource_id"], metadata["contest_id"]) == (contest.resource_id, contest.pk):
                fixture_paths.append(fixture_path)

        if len(fixture_paths) > 1:
            paths = ", ".join(str(self.display_path(path)) for path in fixture_paths)
            raise CommandError(f"multiple parser fixtures for contest id {contest.pk}: {paths}")
        if fixture_paths:
            return fixture_paths[0]
        return fixture_path_for_contest(contest)

    def validate_contest(self, contest):
        if not getattr(contest.resource, "module", None):
            raise CommandError(f"resource {contest.resource.host} has no parser module")

        related = []
        if contest.related_id:
            related.append("related")
        if contest.merging_contests.exists():
            related.append("merging_contests")
        if hasattr(contest, "stage"):
            related.append("stage")
        if related:
            raise CommandError(
                f"contest depends on unsupported related objects ({', '.join(related)}); choose a standalone contest"
            )

    def select_statistics_for_fixture(self, contest):
        statistics = (
            Statistics.objects.filter(contest=contest)
            .select_related("account")
            .order_by(F("place_as_int").asc(nulls_last=True), "pk")
        )
        selected = []
        seen_keys = set()
        for statistic in statistics:
            addition_keys = set(addition_key_paths(statistic.addition or {}))
            new_keys = addition_keys - seen_keys
            if not new_keys:
                continue
            selected.append(statistic)
            seen_keys.update(addition_keys)

        if not selected:
            raise CommandError(
                f"contest {contest.resource.host}/{contest.key} has no saved statistics with addition keys; "
                "parse the contest first or choose another contest"
            )

        context = standings_context_from_statistics(selected)
        self.verbose(
            f"selected {len(selected)} statistic row(s) covering {len(seen_keys)} addition key path(s)",
            level=2,
        )
        self.verbose(f"selected users: {', '.join(context.users)}", level=3)
        self.verbose(f"addition key paths: {', '.join(sorted(seen_keys))}", level=3)
        return SelectedStatistics(
            statistics=selected,
            users=context.users,
            statistics_by_key=context.statistics,
            addition_keys=seen_keys,
        )

    def serialize_database_fixture(self, contest, selected_statistics=None):
        objects = [contest.resource, contest.resource.module, contest]
        if contest.series_id:
            objects.insert(-1, contest.series)
        if selected_statistics:
            accounts = []
            seen_account_ids = set()
            for statistic in selected_statistics:
                if statistic.account_id in seen_account_ids:
                    continue
                accounts.append(statistic.account)
                seen_account_ids.add(statistic.account_id)
            objects.extend(accounts)
            objects.extend(selected_statistics)

        fixture = json.loads(serializers.serialize("json", objects))
        account_ids = {statistic.account_id for statistic in selected_statistics or []}
        for obj in fixture:
            if obj["model"] == "clist.contest":
                obj["fields"].pop("writers", None)
            elif obj["model"] == "ranking.account":
                obj["fields"].pop("coders", None)
                for field in ("duplicate", "related"):
                    if obj["fields"].get(field) not in account_ids:
                        obj["fields"][field] = None
            elif obj["model"] == "ranking.statistics":
                obj["fields"]["related"] = None
        sensitive_paths = []

        def find_sensitive(value, path):
            if isinstance(value, dict):
                for key, item in value.items():
                    item_path = f"{path}.{key}"
                    if item and SENSITIVE_NAME_RE.search(str(key)):
                        sensitive_paths.append(item_path)
                    find_sensitive(item, item_path)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    find_sensitive(item, f"{path}[{index}]")

        find_sensitive(fixture, "db")
        if sensitive_paths:
            paths = ", ".join(sensitive_paths[:5])
            raise CommandError(f"refusing to record potentially sensitive database fields: {paths}")
        return fixture

    def sensitive_values(self):
        values = []
        for name, value in os.environ.items():
            if value and len(value) >= 8 and SENSITIVE_NAME_RE.search(name):
                values.append((name, value.encode()))
        return values

    def format_sensitive_match(self, value):
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="backslashreplace")
        return repr(value)

    def validate_recording(self, fixture_path, show_sensitive_matches=False):
        sensitive_values = self.sensitive_values()
        for path in fixture_path.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_bytes()
            sensitive_match = SENSITIVE_VALUE_RE.search(content)
            if sensitive_match:
                message = f"refusing to keep a potential credential in {path.relative_to(fixture_path)}"
                if show_sensitive_matches:
                    message += (
                        f": regex match at byte {sensitive_match.start()} "
                        f"{self.format_sensitive_match(sensitive_match.group(0))}"
                    )
                raise CommandError(message)

            for name, value in sensitive_values:
                if value not in content:
                    continue
                message = f"refusing to keep an environment secret in {path.relative_to(fixture_path)}"
                if show_sensitive_matches:
                    message += f": environment {name}={self.format_sensitive_match(value)}"
                raise CommandError(message)

    def replace_fixture(self, source, destination):
        backup = destination.with_name(f".{destination.name}.backup")
        if backup.exists():
            raise CommandError(f"stale fixture backup exists: {backup}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        had_destination = destination.exists()
        if had_destination:
            destination.rename(backup)
        try:
            source.rename(destination)
        except Exception:
            if had_destination:
                backup.rename(destination)
            raise
        if had_destination:
            shutil.rmtree(backup)

    def make_fixture_readable(self, fixture_path):
        fixture_path.chmod(0o755)
        for path in fixture_path.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)

    def gzip_file(self, path):
        path = Path(path)
        gzip_path = path.with_suffix(f"{path.suffix}.gz")
        temporary_path = gzip_path.with_suffix(f"{gzip_path.suffix}.tmp")
        with path.open("rb") as input_file, gzip.open(temporary_path, "wb", compresslevel=9) as output_file:
            shutil.copyfileobj(input_file, output_file)
        temporary_path.replace(gzip_path)
        path.unlink()
        return gzip_path

    def compress_fixture_files(self, fixture_path):
        compressed = []
        expected_standings = fixture_path / "expected_standings.json"
        if expected_standings.is_file():
            compressed.append(self.gzip_file(expected_standings))

        for cache_file in sorted((fixture_path / "httpcache").glob("*.html")):
            compressed.append(self.gzip_file(cache_file))

        if compressed:
            self.verbose(f"compressed {len(compressed)} fixture file(s) with gzip", level=2)

    def make_fixture_owned_by_workspace_user(self, fixture_path):
        if not is_effective_root():
            return

        result = chown_tree_to_existing_parent_owner(
            fixture_path,
            owner_source=Path(settings.BASE_DIR),
            root=PARSER_FIXTURES_ROOT,
        )
        if result.skipped_reason:
            self.stderr.write(
                self.style.WARNING(
                    "Could not infer a non-root workspace owner from "
                    f"{self.display_path(result.owner.path)} "
                    f"(uid={result.owner.uid}, gid={result.owner.gid}); "
                    "parser fixture ownership was left unchanged. "
                    "This is expected in copied production checkouts."
                )
            )

    def eligible_contests(self, args=None):
        self.verbose("select eligible contests", level=3)
        contests = (
            Contest.objects.select_related("resource", "series")
            .filter(
                end_time__lt=timezone.now(),
                end_time__gt=timezone.now() - timezone.timedelta(days=365 * 2),
                merging_contests__isnull=True,
                parsed_time__isnull=False,
                resource__module__isnull=False,
                stage__isnull=True,
            )
            .exclude(key="")
        )

        if args:
            if args.contest_id is not None:
                self.verbose(f"filter suggestions by contest id: {args.contest_id}", level=2)
                contests = contests.filter(pk=args.contest_id)
            if args.resource_id is not None:
                self.verbose(f"filter suggestions by resource id: {args.resource_id}", level=2)
                contests = contests.filter(resource_id=args.resource_id)
            if args.resource:
                self.verbose(f"filter suggestions by resource: {args.resource}", level=2)
                resource = Resource.get(args.resource, queryset=Resource.objects.all(), raise_exception=CommandError)
                contests = contests.filter(resource=resource)
            if args.contest_key:
                self.verbose(f"filter suggestions by contest key: {args.contest_key}", level=2)
                contests = contests.filter(key=args.contest_key)

        return contests

    def suggestion_candidates(self, args=None):
        self.verbose("build suggestion candidates", level=2)
        contests = self.eligible_contests(args)
        combination_contests = contests
        if not args or not (
            args.contest_id is not None or args.resource or args.resource_id is not None or args.contest_key
        ):
            self.verbose(f"limit parser-variant audit to default resources: {', '.join(SUGGESTION_RESOURCES)}", level=3)
            combination_contests = combination_contests.filter(resource__host__in=SUGGESTION_RESOURCES)

        combinations = (
            combination_contests.annotate(
                series_is_null=Case(
                    When(series__isnull=True, then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField(),
                )
            )
            .order_by("resource_id", *COVERAGE_QUERY_FIELDS, "-end_time", "-pk")
            .distinct("resource_id", *COVERAGE_QUERY_FIELDS)
        )
        annual = (
            contests.filter(series__slug__in=ANNUAL_SERIES)
            .order_by("series__slug", "-end_time", "-pk")
            .distinct("series__slug")
        )
        return combinations, annual

    def describe_value(self, value):
        if value is True:
            return "yes"
        if value is False:
            return "no"
        if value is None:
            return "unknown"
        return str(value)

    def describe_coverage(self, contest):
        values = contest_coverage_values(contest)
        values["series"] = not values["series"]
        labels = {
            "kind": "kind",
            "standings_kind": "standings",
            "invisible": "hidden",
            "is_rated": "rated",
            "series": "series",
            "with_medals": "medals",
        }
        return ", ".join(f"{labels[name]}={self.describe_value(value)}" for name, value in values.items())

    def write_suggestions_summary(
        self,
        *,
        covered_combination_count,
        n_candidate_combinations,
        covered_annual_count,
        n_candidate_annual_contests,
        suggestions,
        force_update=False,
    ):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Parser fixture coverage"))
        self.stdout.write(f"  parser variants: {covered_combination_count}/{n_candidate_combinations} covered")
        self.stdout.write(f"  annual latest:   {covered_annual_count}/{n_candidate_annual_contests} covered")
        label = "selected" if force_update else "missing"
        missing = f"  {label}:        {len(suggestions)} fixture(s)"
        self.stdout.write(self.style.WARNING(missing) if suggestions else self.style.SUCCESS(missing))

    def write_suggestions(self, suggestions, force_update=False):
        grouped = defaultdict(list)
        for suggestion in suggestions:
            contest = suggestion["contest"]
            grouped[contest.resource.host, contest.resource_id].append(suggestion)

        self.stdout.write("")
        title = "Parser fixtures selected for force update" if force_update else "Missing parser fixtures"
        self.stdout.write(self.style.WARNING(f"{title} ({len(suggestions)})"))
        for (host, resource_id), host_suggestions in grouped.items():
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_LABEL(f"{host} [resource_id={resource_id}] ({len(host_suggestions)})"))
            for suggestion in host_suggestions:
                contest = suggestion["contest"]
                self.stdout.write(f"  - contest_id={contest.pk}, key={contest.key} — {contest.title}")
                for reason_type, detail in suggestion["reasons"]:
                    if reason_type in {"combination", "force-update-combination"}:
                        prefix = "update variant" if reason_type.startswith("force-update") else "variant"
                        self.stdout.write(f"    {prefix}: {detail}")
                    elif reason_type in {"annual", "force-update-annual"}:
                        prefix = "update annual" if reason_type.startswith("force-update") else "annual"
                        self.stdout.write(f"    {prefix}:  series={detail}")
                    else:
                        self.stdout.write(f"    {reason_type}: {detail}")

    def suggest_fixtures(
        self,
        args=None,
        update=False,
        show_sensitive_matches=False,
        fail_fast=False,
        show_error_traceback=False,
        show_error_locals=False,
        force_update=False,
    ):
        self.verbose("load existing parser fixture coverage", level=2)
        covered_combinations, covered_contests = load_fixture_coverage()
        combination_candidates, annual_candidates = self.suggestion_candidates(args)
        combination_candidates = list(combination_candidates)
        annual_candidates = list(annual_candidates)
        self.verbose(
            f"candidate counts: parser variants={len(combination_candidates)}, annual latest={len(annual_candidates)}",
            level=3,
        )

        suggestions = {}
        covered_combination_count = 0
        for contest in combination_candidates:
            covered = contest_coverage_key(contest) in covered_combinations
            if covered:
                covered_combination_count += 1
            if force_update or not covered:
                reason_type = "force-update-combination" if covered else "combination"
                suggestions.setdefault(contest.pk, {"contest": contest, "reasons": []})["reasons"].append((
                    reason_type,
                    self.describe_coverage(contest),
                ))

        covered_annual_count = 0
        for contest in annual_candidates:
            covered = (contest.resource_id, contest.pk) in covered_contests
            if covered:
                covered_annual_count += 1
            if force_update or not covered:
                reason_type = "force-update-annual" if covered else "annual"
                suggestions.setdefault(contest.pk, {"contest": contest, "reasons": []})["reasons"].append((
                    reason_type,
                    contest.series.slug,
                ))

        suggestions = list(suggestions.values())
        self.write_suggestions_summary(
            covered_combination_count=covered_combination_count,
            n_candidate_combinations=len(combination_candidates),
            covered_annual_count=covered_annual_count,
            n_candidate_annual_contests=len(annual_candidates),
            suggestions=suggestions,
            force_update=force_update,
        )

        if not suggestions:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("No parser fixtures need to be added."))
            return

        self.write_suggestions(suggestions, force_update=force_update)

        if update:
            action = "selected fixtures" if force_update else "suggested missing fixtures"
            self.verbose(f"record {action}", level=2)
            self.record_suggestions(
                suggestions,
                show_sensitive_matches=show_sensitive_matches,
                fail_fast=fail_fast,
                show_error_traceback=show_error_traceback,
                show_error_locals=show_error_locals,
            )

    def record_suggestions(
        self,
        suggestions,
        show_sensitive_matches=False,
        fail_fast=False,
        show_error_traceback=False,
        show_error_locals=False,
    ):
        suggestions = list(suggestions)
        failures = []
        n_attempted = 0

        for index, suggestion in enumerate(suggestions, start=1):
            n_attempted += 1
            contest = suggestion["contest"]
            self.stdout.write(
                self.style.HTTP_INFO(f"[{index}/{len(suggestions)}] Recording {contest.resource.host}/{contest.key}")
            )
            try:
                self.verbose("validate contest constraints", level=2)
                self.validate_contest(contest)
                fixture_path = self.fixture_path_for_recording(contest)
                self.verbose(f"fixture path: {self.display_path(fixture_path)}", level=2)
                self.record_fixture(contest, fixture_path, show_sensitive_matches=show_sensitive_matches)
            except Exception as error:
                failures.append((contest, error))
                self.stderr.write(
                    self.style.ERROR(
                        f"[{index}/{len(suggestions)}] Failed {contest.resource.host}/{contest.key}: "
                        f"{type(error).__name__}: {error}"
                    )
                )
                if show_error_traceback or show_error_locals:
                    self.stderr.write(self.dim(self.format_error_traceback(error, show_locals=show_error_locals)))
                if fail_fast:
                    self.stderr.write(self.style.ERROR("Stopping after first failure because --fail-fast is set."))
                    break
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"[{index}/{len(suggestions)}] Recorded {contest.resource.host}/{contest.key}")
                )

        n_recorded = n_attempted - len(failures)
        n_skipped = len(suggestions) - n_attempted
        status = "stopped" if n_skipped else "completed"
        summary = f"Batch recording {status}: {n_recorded} recorded, {len(failures)} failed"
        if n_skipped:
            summary += f", {n_skipped} skipped"
        if failures:
            self.stdout.write(self.style.WARNING(summary))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
        if failures:
            failed_contests = ", ".join(f"{contest.resource.host}/{contest.key}" for contest, _ in failures)
            if n_skipped:
                raise CommandError(
                    f"failed to record {len(failures)} of {n_attempted} attempted fixtures "
                    f"({n_skipped} skipped): {failed_contests}"
                )
            raise CommandError(f"failed to record {len(failures)} of {len(suggestions)} fixtures: {failed_contests}")

    def record_fixture(self, contest, fixture_path, show_sensitive_matches=False):
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = Path(tempfile.mkdtemp(prefix=f".{fixture_path.name}.recording-", dir=fixture_path.parent))
        try:
            self.verbose(f"temporary recording directory: {self.display_path(temporary_path)}", level=3)
            cache_path = temporary_path / "httpcache"
            self.verbose("prepare temporary HTTP cache", level=2)
            cache_path.mkdir()
            selected_statistics = self.select_statistics_for_fixture(contest)

            self.verbose("run parser with network enabled", level=2)
            standings = get_standings(
                contest,
                cache_path,
                allow_network=True,
                users=selected_statistics.users,
                statistics=selected_statistics.statistics_by_key,
            )
            self.verbose(f"live standings: {self.describe_standings(standings)}", level=3)
            if "result" not in standings:
                raise CommandError(f"parser returned no result snapshot: {sorted(standings)}")
            self.verbose("serialize database fixture", level=2)
            write_json(
                temporary_path / "db.json",
                self.serialize_database_fixture(contest, selected_statistics.statistics),
            )
            self.verbose("write golden standings snapshot", level=2)
            write_expected_standings(temporary_path, standings)

            cache_files = [path for path in cache_path.iterdir() if path.is_file()]
            html_cache_files = list(cache_path.glob("*.html"))
            self.verbose(f"HTTP cache files: {len(cache_files)} total, {len(html_cache_files)} html", level=3)
            if not html_cache_files:
                raise CommandError("parser made no cacheable HTTP requests")

            self.verbose("run immediate offline replay", level=2)
            replayed = get_standings(
                contest,
                cache_path,
                allow_network=False,
                users=selected_statistics.users,
                statistics=selected_statistics.statistics_by_key,
            )
            self.verbose(f"offline standings: {self.describe_standings(replayed)}", level=3)
            self.verbose("compare live and offline normalized standings", level=2)
            self.assert_same_normalized_standings(
                standings,
                replayed,
                "recorded standings differ from the immediate offline replay",
            )

            self.verbose("scan fixture for credentials", level=2)
            self.validate_recording(temporary_path, show_sensitive_matches=show_sensitive_matches)
            self.verbose("compress fixture files", level=2)
            self.compress_fixture_files(temporary_path)
            self.verbose("run compressed offline replay", level=2)
            replayed = get_standings(
                contest,
                cache_path,
                allow_network=False,
                users=selected_statistics.users,
                statistics=selected_statistics.statistics_by_key,
            )
            self.verbose(f"compressed offline standings: {self.describe_standings(replayed)}", level=3)
            self.verbose("compare live and compressed offline normalized standings", level=2)
            self.assert_same_normalized_standings(
                standings,
                replayed,
                "compressed fixture standings differ from the live recording",
            )
            self.verbose("make fixture files readable", level=3)
            self.make_fixture_readable(temporary_path)
            self.verbose(f"replace fixture at {self.display_path(fixture_path)}", level=2)
            self.replace_fixture(temporary_path, fixture_path)
            self.verbose("make fixture owned by workspace user", level=3)
            self.make_fixture_owned_by_workspace_user(fixture_path)
        finally:
            if temporary_path.exists():
                self.verbose(f"remove temporary recording directory: {self.display_path(temporary_path)}", level=3)
                shutil.rmtree(temporary_path)

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        args = AttrDict(options)
        self.set_verbosity(args.verbosity)

        if args.suggest:
            self.suggest_fixtures(
                args=args,
                update=args.update,
                show_sensitive_matches=args.show_sensitive_matches,
                fail_fast=args.fail_fast,
                show_error_traceback=args.traceback or args.verbosity >= 2,
                show_error_locals=args.show_error_locals,
                force_update=args.force_update,
            )
            return

        contest = self.get_contest(args)
        self.verbose(f"selected contest: {contest.resource.host}/{contest.key}", level=2)
        self.validate_contest(contest)
        fixture_path = self.fixture_path_for_recording(contest)
        self.verbose(f"fixture path: {self.display_path(fixture_path)}", level=2)

        if args.update:
            for required in ("db.json", "expected_standings.json"):
                if not fixture_file_path(fixture_path, required).exists():
                    raise CommandError(f"fixture is incomplete, missing {required}: {fixture_path}")
            if not (fixture_path / "httpcache").is_dir():
                raise CommandError(f"fixture is incomplete, missing httpcache: {fixture_path}")
            selected_statistics = self.select_statistics_for_fixture(contest)
            self.verbose("replay existing fixture cache offline", level=2)
            standings = get_standings(
                contest,
                fixture_path / "httpcache",
                allow_network=False,
                users=selected_statistics.users,
                statistics=selected_statistics.statistics_by_key,
            )
            self.verbose(f"offline standings: {self.describe_standings(standings)}", level=3)
            self.verbose("write database fixture with selected statistics", level=2)
            write_json(
                fixture_path / "db.json",
                self.serialize_database_fixture(contest, selected_statistics.statistics),
            )
            self.verbose("write golden standings snapshot", level=2)
            write_expected_standings(fixture_path, standings, compressed=True)
            raw_expected_standings = fixture_path / "expected_standings.json"
            if raw_expected_standings.exists():
                raw_expected_standings.unlink()
            action = "Updated"
        else:
            self.record_fixture(contest, fixture_path, show_sensitive_matches=args.show_sensitive_matches)
            action = "Recorded"

        relative_path = (
            fixture_path.relative_to(Path.cwd()) if fixture_path.is_relative_to(Path.cwd()) else fixture_path
        )
        self.stdout.write(self.style.SUCCESS(f"{action} parser fixture: {relative_path}"))
