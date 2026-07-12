---
name: add-management-command
description: >-
  Use when adding or fixing a batch Django management command under
  src/ranking/management/commands/ — wiring add_arguments, the CLIST
  command skeleton (AttrDict(options), getLogger, print_sql_decorator), the
  EventLog/failed_on_exception monitoring idiom, Resource.get() host filtering,
  or wiring a cron entry with a Healthchecks monitor in config/cron. Keywords:
  management command, BaseCommand, add_arguments, cron, Healthchecks monitor,
  run-manage.bash, EventLog, tqdm.
---

# Add a CLIST management command (+ cron/Healthchecks monitor)

Management commands live in `src/ranking/management/commands/` (16 existing).
They back the cron schedule (`config/cron`) and the RQ workers. **Always read
2–3 similar ones first** — `set_account_rank.py`, `set_country_fields.py`, and
`anonymize_accounts.py` are the cleanest references.

## The CLIST skeleton (copy this)

```python
#!/usr/bin/env python3

from logging import getLogger

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from django_print_sql import print_sql_decorator
from tqdm import tqdm

from clist.models import Resource
from ranking.models import Account
from utils.attrdict import AttrDict


class Command(BaseCommand):
    help = 'One-line description'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = getLogger('ranking.<command_name>')

    def add_arguments(self, parser):
        parser.add_argument('-r', '--resources', metavar='HOST', nargs='*', help='resources hosts')
        parser.add_argument('-n', '--limit', type=int, help='number of items to process')
        parser.add_argument('--verbose', action='store_true', help='verbose output')

    @print_sql_decorator(count_only=True)
    def handle(self, *args, **options):
        self.stdout.write(str(options))           # ALWAYS first line
        args = AttrDict(options)

        resources = Resource.available_for_update_objects.all()
        if args.resources:
            resources = Resource.get(args.resources, queryset=resources)   # host + short_host aware
        if args.limit:
            resources = resources[:args.limit]

        for resource in tqdm(resources, total=len(resources), desc='resources'):
            ... work ...
```

### Why each piece

| Piece | Why |
|-------|-----|
| `self.logger = getLogger('ranking.<name>')` in `__init__` | Lets workers/cron capture per-command logs. Naming: `<app>.<command>` is dominant; use `<app>.<cluster>.<name>` (e.g. `ranking.parse.statistic`) for a related subgroup. |
| `self.stdout.write(str(options))` as the **first** line of `handle` | Echoes parsed flags into the run log — essential for `EventLog` forensics and cron debugging. Universally present. |
| `args = AttrDict(options)` right after | `AttrDict` (`utils/attrdict.py`) makes every key an attribute — `args.resources` not `options['resources']`. Pervasive. |
| `@print_sql_decorator(count_only=True)` on `handle` | Counts DB queries without dumping SQL. Optional but very common. |
| `.save(..., update_fields=[...])` everywhere | Never call `.save()` without `update_fields` in a command — avoids clobbering concurrent updates and shrinks the query. |

## EventLog monitoring (when iterating over resources/contests)

Wrap **per-item** work so a failure on one item is recorded, not fatal. One
`EventLog` per loop iteration, not per command:

```python
from logify.models import EventLog, EventStatus
from logify.utils import failed_on_exception

for resource in tqdm(resources, total=len(resources), desc='resources'):
    event_log = EventLog.objects.create(
        name='set_account_rank',
        related=resource,                       # GenericForeignKey — any model instance
        status=EventStatus.IN_PROGRESS,
    )
    with failed_on_exception(event_log):        # sets FAILED + re-raises on error
        ... work ...
        event_log.update_message(message)       # progressive status, optional
    event_log.update_status(EventStatus.COMPLETED, message=message)   # runs only on success
```

`EventStatus` values: `NONE`, `COMPLETED`, `FAILED`, `IN_PROGRESS`, `CANCELLED`,
`SKIPPED`, `INTERRUPTED`, `WARNING`. For a lighter auto-complete helper, see
`logging_event(**kwargs)` in `src/logify/utils.py`.

## Filtering by host — prefer `Resource.get()`

```python
resources = Resource.get(args.resources, queryset=resources)
```

`Resource.get()` (`src/clist/models.py:516`) handles `host` / `short_host` / pk
matching, validates all entries resolve, and accepts a `queryset=`. Reach for the
manual `Q()` OR-accumulation only if you need `__iregex`:

```python
resource_filter = Q()
for r in args.resources:
    resource_filter |= Q(host__iregex=r) | Q(short_host=r)
resources = resources.filter(resource_filter)
```

## Reused helpers worth knowing

- `Resource.available_for_update_objects` — manager that yields only
  update-eligible resources. Start update commands from it, not `Resource.objects`.
- `utils.timetools.parse_duration` — accept time-delay args as readable strings
  (`'5 days'`), parse at the call site. House convention for recency filters.
- `utils.logger.suppress_db_logging_context` — **always** wrap bulk writes so the
  inner loop doesn't flood logs with per-query SQL:
  ```python
  with suppress_db_logging_context():
      Account.objects.bulk_update(batch, update_fields)
  ```
- `utils.json_field.{Cast,Json,Integer,Float,Char}JSONF` — cast typed values out
  of `info` / `addition` JSONFields inside annotations/filters (e.g.
  `FloatJSONF('addition__new_rating')`).
- `clist.templatetags.extras.get_item` — safe nested-dict lookup.

## Argument gotchas

- **`-n` is overloaded.** It means `--limit` (count) in ranking commands and
  `--dryrun` in `anonymize_accounts`/`detect_major_contests`. Match the command's
  semantics; don't blindly inherit.
- Common shared flags: `-r/--resources` (`metavar='HOST'`, `nargs='*'`),
  `-l/--limit`, `-q/--query|search`, `--verbose`, `--force`, `--dryrun`. Add a
  `--dryrun` (gated by `if args.dryrun: continue` before `.save()` calls) for any
  mutating command.

## Wiring a cron entry + Healthchecks monitor

Cron jobs live in `config/cron` and go through `src/run-manage.bash`, which flocks
on `/tmp/<name>.lock`, loads `/run/secrets/monitoring_conf`, tees to
`logs/manage/<name>.log`, and optionally pings a self-hosted **Healthchecks**
check (dead-man's-switch):

```
<schedule>  env MONITOR_NAME=<check-slug>  /usr/src/clist/run-manage.bash <command> [args]
```

- `MONITOR_NAME` is the Healthchecks **check slug** (kebab-case). `run-manage.bash`
  builds the ping URL as `$HEALTHCHECKS_PING_URL/$HEALTHCHECKS_PING_KEY/<slug>`
  (both vars come from `.env.monitoring`), sends `/start?create=1` before the
  command and `/<exit-code>` after — so the check is **auto-created on first
  ping**; set its schedule/grace in the Healthchecks UI afterwards.
- If no monitor is needed, omit the `env MONITOR_NAME=...` prefix — the command
  still runs (logged + flocked).
- Existing slugs: `parsing-statistics`, `parsing-accounts`, `calendar-update`,
  `sending-notifications`, `creating-notifications`, `checking-logs`,
  `set-account-rank`, `set-country-fields`, `update-auto-rating`,
  `parse-archive-problems`, `check-schedule-parsing` (see `config/cron`).

## Test loop (safe, narrow)

Re-run in the dev container against a single resource, with verbose + dry-run if
available:

```bash
docker compose exec dev ./manage.py <command> -r <one-host> --verbose
docker compose exec dev ./manage.py <command> -r <one-host> --dryrun   # if defined
```

Inspect `EventLog` rows (`django_admin` or shell) for status/messages. For the
broader verify step (lint, tests), see the [`run-and-verify`](../run-and-verify/SKILL.md)
skill.

## When done, report

Command file added/changed, argument surface, whether an `EventLog`/cron/Healthchecks
entry was wired, the exact verification command(s) run + result, and any manual
DB step still needed.
