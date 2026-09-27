---
name: add-management-command
description: >-
  Add or change a CLIST Django management command, including arguments,
  resource selection, EventLog monitoring, or cron and Healthchecks wiring.
  Applies to commands under src/*/management/commands/.
---

# Add or change a management command

Read two nearby commands with similar behavior before editing. For batch
resource updates, `set_account_rank.py` and `set_country_fields.py` show the
current conventions; `anonymize_accounts.py` shows a command with an explicit
dry-run option. A command does not need a cron entry or EventLog merely because
other commands use them.

## Command behavior

- Use Django's `BaseCommand`, `add_arguments`, and `handle`. Match the
  surrounding command's option names and logging style.
- `Resource.get(values, queryset=...)` resolves host, short host, or ID and
  rejects unmatched values. Use `Resource.available_for_update_objects` when
  the operation should target only update-eligible resources.
- `AttrDict(options)` and `@print_sql_decorator(count_only=True)` are optional
  project conventions. Log selected arguments when useful, but do not log raw
  `options` if they may contain credentials or personal data.
- Use `save(update_fields=[...])` when only known fields changed, so concurrent
  updates to unrelated fields are preserved. Choose bulk writes only when the
  command's behavior and database load justify them.
- A `--dryrun` option is useful for consequential writes only if every write
  path actually honors it. Do not describe `--verbose` or a partial skip flag
  as a dry run.

## EventLog

Choose the helper that matches the command. See `src/logify/utils.py` and
`src/logify/live.py`:

- `failed_on_exception(event_log)` marks failure and re-raises; mark completion
  yourself on success.
- `logging_event(**kwargs)` creates one event and completes it on success.
- `stream_event_log(event_log, logger)` also streams progress and completes
  an in-progress event on success.

A per-resource event is useful when individual failures need to be visible.
A simpler command may only need normal logging. Check status transitions
against `EventStatus` before adding a new pattern.

## Cron and Healthchecks

If the command needs scheduling, add it to `config/cron` through
`src/run-manage.bash`. Existing monitored entries use this shape:

```text
<schedule> env MONITOR_NAME=<slug> /usr/src/clist/run-manage.bash <command> [args]
```

A monitor is optional. With `MONITOR_NAME`, the runner sends start and result
pings but **does not create the check**. Add the same slug, schedule, grace,
and description to `config/healthchecks/provision.py`. That file is applied
separately to the Healthchecks container; see
[docs/infrastructure.md](../../../docs/infrastructure.md) for the
provisioning command. Keep the cron schedule and provisioned schedule aligned.
Do not edit live monitoring settings unless the task includes that operation.

## Verify and report

Run `docker compose exec dev ./manage.py <command> --help` and focused tests.
Run the command itself only after checking its effects and selecting an
appropriate target; a limited resource or `--dryrun` flag is safe only if the
implementation supports that claim. Use
[run-and-verify](../run-and-verify/SKILL.md) for Python checks. Report the
command, arguments, tests, and any cron or provisioning step still needed.
