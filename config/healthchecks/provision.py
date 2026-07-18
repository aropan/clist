"""Declarative provisioning for CLIST's self-hosted Healthchecks.

Provisions the config Healthchecks keeps in its database, not in Django settings:
ping retention, per-check schedule / grace / description, and the Telegram alert
channel. Scalar knobs are read from the environment (HC_* / TELEGRAM_* in
.env.healthchecks); the per-check schedule table lives in MONITORS below. Applied
idempotently.

This file is mounted into the healthchecks container; it is NOT applied
automatically. Run it by hand after editing (or after adding a monitored cron):

    docker compose exec healthchecks sh -c 'python manage.py shell < /opt/healthchecks/provision.py'

Notes
-----
* This script is the only thing that creates checks (name == slug == MONITOR_NAME, see
  config/cron); run-manage.bash only pings existing checks (no `create=1`), so run it
  after adding a monitored cron, before that cron's pings start.
* The prod container that runs config/cron is on UTC, so schedules use tz "UTC".
* run-manage.bash uses `flock -n` and sends no ping when a run is skipped because the
  previous one is still running, so `grace` is set generously to absorb skipped runs
  and occasional overruns without false DOWN alerts.
* Telegram is provisioned as an outbound-only channel with a known chat_id; we never
  register a Telegram webhook, so the ClistBot production webhook stays intact.
"""

import json
import os
import sys
from datetime import timedelta

from django.conf import settings
from django.utils.text import slugify
from hc.accounts.models import Profile, Project
from hc.api.models import Channel, Check

# --- retention -------------------------------------------------------------

# Pings kept per check (Healthchecks default is 100); see HC_PING_LOG_LIMIT in
# .env.healthchecks.template. Only failed pings carry a body (run-manage.bash posts
# the log tail), so extra rows stay cheap.
PING_LOG_LIMIT = int(os.environ["HC_PING_LOG_LIMIT"])

# --- schedules -------------------------------------------------------------

# Timezone the cron schedules below are written in (prod container runs on UTC).
TZ = os.environ["HC_TZ"]

# MONITOR_NAME -> (cron schedule, grace, description). Mirrors config/cron.
MONITORS = {
    "parsing-statistics": (
        "* * * * *",
        timedelta(minutes=15),
        "parse_statistic --split-by-resource: pulls contest standings every minute.",
    ),
    "creating-notifications": (
        "* * * * *",
        timedelta(minutes=10),
        "notification_to_task: turns due notifications into send tasks every minute.",
    ),
    "sending-notifications": (
        "* * * * *",
        timedelta(minutes=10),
        "sendout_tasks: delivers queued notification tasks every minute.",
    ),
    "checking-logs": (
        "* * * * *",
        timedelta(minutes=10),
        "check_logs: scans management-command logs for errors every minute.",
    ),
    "parsing-accounts": (
        "*/3 * * * *",
        timedelta(minutes=20),
        "parse_accounts_infos --split-by-resource: refreshes account info every 3 min.",
    ),
    "check-schedule-parsing": (
        "*/15 * * * *",
        timedelta(minutes=20),
        "check_schedule_parsing: detects broken schedule parsers every 15 min.",
    ),
    "set-account-rank": (
        "*/15 * * * *",
        timedelta(minutes=100),
        "set_account_rank: recomputes account ranks every 15 min.",
    ),
    "set-country-fields": (
        "*/20 * * * *",
        timedelta(minutes=25),
        "set_country_fields: backfills account country fields every 20 min.",
    ),
    "calendar-update": (
        "20,35,55 * * * *",
        timedelta(minutes=35),
        "update_google_calendars: syncs Google calendars at :20, :35 and :55.",
    ),
    "parse-archive-problems": (
        "30 * * * *",
        timedelta(minutes=40),
        "parse_archive_problems: imports archive problems hourly at :30.",
    ),
    "update-auto-rating": (
        "15 * * * *",
        timedelta(minutes=40),
        "update_auto_rating: recomputes auto ratings hourly at :15.",
    ),
}

# --- telegram --------------------------------------------------------------

# Alert target chat: HC_ALERT_CHAT_ID is ClistBot's admin chat (conf.py
# TELEGRAM_ADMIN_CHAT_ID); HC_ALERT_CHAT_TYPE is "private" for a 1:1 chat, or
# "group" / "supergroup" for a group the bot is a member of.
TELEGRAM_CHAT_ID = int(os.environ["HC_ALERT_CHAT_ID"])
TELEGRAM_CHAT_TYPE = os.environ["HC_ALERT_CHAT_TYPE"]

# --- output helpers --------------------------------------------------------

USE_COLOR = sys.stdout.isatty()


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def show(value):
    """Compact, terminal-friendly rendering of a field value."""
    if isinstance(value, timedelta):
        minutes, seconds = divmod(int(value.total_seconds()), 60)
        return f"{minutes}m" if not seconds else f"{minutes}m{seconds}s"
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def status(created, changed):
    if created:
        return paint("created".ljust(9), "32")  # green
    if changed:
        return paint("updated".ljust(9), "33")  # yellow
    return paint("unchanged".ljust(9), "90")  # grey


def row(created, changed, name, detail):
    print(f"  {status(created, changed)}  {name.ljust(COL)}  {detail}")


# ---------------------------------------------------------------------------

project = Project.objects.order_by("id").first()  # single-user instance -> one project
if project is None:
    # Fresh instance: the first REMOTE_USER login creates the user and project.
    print("no Healthchecks project yet; skipping (log in once, then re-run)")
    raise SystemExit(0)

COL = max(len(name) for name in MONITORS)

print(paint("Healthchecks provisioning", "1"))

# 1) retention (per profile; single user -> single profile)
old_limit = project.owner_profile.ping_log_limit
Profile.objects.update(ping_log_limit=PING_LOG_LIMIT)
changed = old_limit != PING_LOG_LIMIT
detail = f"ping_log_limit: {old_limit} -> {PING_LOG_LIMIT}" if changed else f"ping_log_limit={PING_LOG_LIMIT}"
row(False, changed, "retention", detail)

# 2) Telegram alert channel (created only if a bot token is configured)
if settings.TELEGRAM_TOKEN:
    value = json.dumps(
        {
            "id": TELEGRAM_CHAT_ID,
            "type": TELEGRAM_CHAT_TYPE,
            "name": settings.TELEGRAM_BOT_NAME,
        }
    )
    channel, created = Channel.objects.get_or_create(
        project=project,
        kind="telegram",
        defaults={"value": value, "name": settings.TELEGRAM_BOT_NAME},
    )
    changed = not created and channel.value != value
    if changed:
        channel.value = value
        channel.save(update_fields=["value"])
    row(created, changed, "telegram", f"chat={TELEGRAM_CHAT_ID} type={TELEGRAM_CHAT_TYPE}")
else:
    print(f"  {paint('skipped'.ljust(9), '90')}  {'telegram'.ljust(COL)}  TELEGRAM_TOKEN not set")

# 3) checks: create if missing, pin schedule / tz / grace / desc, then wire channels
print(paint("checks", "1"))
for name, (schedule, grace, desc) in MONITORS.items():
    check, created = Check.objects.get_or_create(
        project=project,
        name=name,
        defaults={"slug": slugify(name)},
    )
    wanted = {
        "slug": check.slug or slugify(name),
        "kind": "cron",
        "schedule": schedule,
        "tz": TZ,
        "grace": grace,
        "desc": desc,
    }
    changes = []
    for field, new in wanted.items():
        old = getattr(check, field)
        if old != new:
            changes.append(f"{field}={show(new)}" if created else f"{field}: {show(old)} -> {show(new)}")
        setattr(check, field, new)
    check.save()

    before = set(check.channel_set.values_list("id", flat=True))
    check.assign_all_channels()
    after = set(check.channel_set.values_list("id", flat=True))
    if before != after:
        changes.append(f"channels={len(after)}")

    row(created, changes, name, ", ".join(changes))

print(paint("done", "1"))
