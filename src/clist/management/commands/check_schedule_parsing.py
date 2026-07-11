#!/usr/bin/env python3

import contextlib
import hashlib
import json
import os
import tempfile
from logging import getLogger

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_print_sql import print_sql_decorator

from clist.models import Contest, Resource
from clist.templatetags.extras import md_escape
from logify.models import EventLog, EventStatus
from tg.bot import Bot
from utils.attrdict import AttrDict
from utils.timetools import datetime_from_timestamp, parse_duration


class Command(BaseCommand):
    help = "Check per-resource schedule parsing stats written by legacy update.php"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger("clist.check_schedule_parsing")

    def add_arguments(self, parser):
        parser.add_argument("--stats-file", default="logs/legacy/update_stats.json", help="stats json from update.php")
        parser.add_argument("--cache-file", default="logs/check_schedule_parsing.yaml", help="state cache yaml")
        parser.add_argument("--stale-threshold", default="2 hours", help="alert if the last run is older")
        parser.add_argument("--window", default="7 days", help="how recently a resource must have produced contests")
        parser.add_argument("-r", "--resources", metavar="HOST", nargs="*", help="resources hosts")
        parser.add_argument("--verbose", action="store_true", help="verbose output")
        parser.add_argument("--dryrun", action="store_true", help="do not alert, create event logs or write state")

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))
        args = AttrDict(options)

        if args.verbose:
            self.logger.setLevel("DEBUG")

        now = timezone.now()
        stale_threshold = parse_duration(args.stale_threshold)
        window = parse_duration(args.window)

        state = {}
        if os.path.exists(args.cache_file):
            try:
                with open(args.cache_file, encoding="utf-8") as fo:
                    state = yaml.safe_load(fo)
            except Exception as e:
                self.logger.error(f"Failed to load cache file {args.cache_file}: {e}")
        if not isinstance(state, dict):
            state = {}
        if "resources" not in state or not isinstance(state["resources"], dict):
            state["resources"] = {}
        resources_state = state["resources"]

        # Pre-fetch only enabled resources (enable=True)
        enabled_resource_ids = set(Resource.objects.filter(enable=True).values_list("pk", flat=True))

        selected_ids = None
        if args.resources:
            selected_ids = set(Resource.get(args.resources, raise_exception=CommandError).values_list("pk", flat=True))

        stats = None
        run_error = None
        try:
            with open(args.stats_file, encoding="utf-8") as fo:
                stats = json.load(fo)
            if not isinstance(stats, dict):
                raise ValueError("stats is not a valid JSON object")
            if "finished_at" not in stats:
                raise KeyError("missing 'finished_at' key")
            if "resources" not in stats or not isinstance(stats["resources"], list):
                raise KeyError("missing or invalid 'resources' key")
            finished_time = datetime_from_timestamp(stats["finished_at"])
        except Exception as e:
            run_error = f"failed to read stats file {args.stats_file}: {e}"
        else:
            if now - finished_time > stale_threshold:
                run_error = (
                    f"last schedule update finished {finished_time:%Y-%m-%d %H:%M:%S},"
                    f" more than {args.stale_threshold} ago"
                )

        alerts = []
        event_resources = []
        if run_error:
            self.logger.warning(run_error)
            run_alert_hash = hashlib.md5(run_error.encode("utf8")).hexdigest()
            if state.get("run_alert_hash") != run_alert_hash:
                state["run_alert_hash"] = run_alert_hash
                alerts.append(run_error)
        else:
            state.pop("run_alert_hash", None)

            # Identify which resource IDs need to query the database to check if contests exists
            rids_to_query = []
            for entry in stats.get("resources", []):
                if not isinstance(entry, dict) or "rid" not in entry:
                    continue
                rid = entry["rid"]
                if not isinstance(rid, int):
                    continue
                if rid in enabled_resource_ids and (selected_ids is None or rid in selected_ids):
                    rstate = resources_state.get(rid)
                    if not isinstance(rstate, dict):
                        rstate = {}
                    if "last_nonzero_at" not in rstate or "last_upserted_at" not in rstate:
                        rids_to_query.append(rid)
            recent_resource_ids = set()
            if rids_to_query:
                recent_resource_ids = set(
                    Contest.objects
                    .filter(resource_id__in=rids_to_query, auto_updated__gte=now - window)
                    .values_list("resource_id", flat=True)
                    .distinct()
                )

            for entry in stats.get("resources", []):
                if not isinstance(entry, dict) or "rid" not in entry or "host" not in entry:
                    continue
                rid = entry["rid"]
                if not isinstance(rid, int):
                    continue
                if rid not in enabled_resource_ids:
                    continue
                if selected_ids is not None and rid not in selected_ids:
                    continue
                host = entry["host"]
                try:
                    n_parsed = int(entry.get("n_contests_parsed", 0))
                    n_upserted = int(entry.get("n_contests_upserted", 0))
                except (ValueError, TypeError):
                    continue

                if rid not in resources_state or not isinstance(resources_state[rid], dict):
                    resources_state[rid] = {}
                resource_state = resources_state[rid]

                problem = None
                if n_parsed == 0:
                    if "last_nonzero_at" in resource_state:
                        recently_produced = datetime_from_timestamp(resource_state["last_nonzero_at"]) >= now - window
                    else:
                        recently_produced = rid in recent_resource_ids
                    if recently_produced:
                        problem = f"{host}: no contests parsed"
                else:
                    resource_state["last_nonzero_at"] = stats["finished_at"]
                    if n_upserted > 0:
                        resource_state["last_upserted_at"] = stats["finished_at"]
                    else:
                        if "last_upserted_at" in resource_state:
                            recently_upserted = (
                                datetime_from_timestamp(resource_state["last_upserted_at"]) >= now - window
                            )
                        else:
                            recently_upserted = rid in recent_resource_ids

                        if recently_upserted:
                            problem = f"{host}: {n_parsed} contests parsed but none upserted"

                if problem:
                    self.logger.warning(problem)
                    alert_hash = hashlib.md5(problem.encode("utf8")).hexdigest()
                    if resource_state.get("alert_hash") != alert_hash:
                        resource_state["alert_hash"] = alert_hash
                        alerts.append(problem)
                        event_resources.append((rid, problem))
                else:
                    resource_state.pop("alert_hash", None)
                    self.logger.debug(f"{host}: parsed = {n_parsed}, upserted = {n_upserted}")

        if alerts:
            message = md_escape("schedule parsing problems") + "\n```\n" + "\n".join(alerts) + "\n```"
            if args.dryrun:
                self.logger.info(f"dryrun, skip alerting:\n{message}")
            else:
                Bot().admin_message(message)
                resources = Resource.objects.in_bulk([rid for rid, _ in event_resources])
                for rid, problem in event_resources:
                    resource = resources.get(rid)
                    if resource is None:
                        continue
                    EventLog.objects.create(
                        name="check_schedule_parsing",
                        related=resource,
                        status=EventStatus.WARNING,
                        message=problem,
                    )
        else:
            self.logger.info("no schedule parsing problems")

        if not args.dryrun:
            cache_dir = os.path.dirname(args.cache_file) or "."
            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile("w", dir=cache_dir, delete=False, encoding="utf-8") as tf:
                    tmp_name = tf.name
                    yaml.dump(state, tf, default_flow_style=False)
                os.replace(tmp_name, args.cache_file)
            except Exception as e:
                if tmp_name and os.path.exists(tmp_name):
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_name)
                self.logger.error(f"Failed to write cache file {args.cache_file}: {e}")
