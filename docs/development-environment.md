# Development environment

← [AGENTS.md](../AGENTS.md)

## The dev container is long-running

The app runs in **Docker Compose**. The **`dev` service** is long-running: it hosts
`runserver` + RQ workers. Run Django management commands **inside** it — do **not**
start a second server.

```bash
# Run any management command in the running dev container:
docker compose exec dev ./manage.py <command>

# Start the dev stack (only if it isn't already up):
docker compose up dev

# App: http://localhost:10042/  (see README.md for first-time setup via configure.py)
```

## Useful shells

```bash
docker compose exec dev ./manage.py shell        # Django shell
docker compose exec dev ./manage.py migrate
docker compose exec dev ./manage.py makemigrations <app>
```

Do not start long-running services without saying what will run and why.

## Management commands

Defined in [`src/ranking/management/commands/`](../src/ranking/management/commands/).
The most common ones:

| Command | Purpose |
|---------|---------|
| `parse_statistic` | The well-known contest-scraper entry point (see [parsers.md](parsers.md)) |
| `dump_parser_fixture` | Record or update an offline parser regression fixture |
| `parse_accounts_infos` | Refresh account info (RQ-scheduled) |
| `parse_live_statistics` | Parse live/running contest statistics |
| `parse_finalists` | Parse finalists (`Finalist` / `FinalistResourceInfo`) |
| `link_accounts_and_coders` | Match `Account` ↔ `Coder` by slug/IOU |
| `link_statistics` | Link `Account` ↔ `Statistics` |
| `set_account_rank` | Per-resource rank computation |
| `set_country_fields` | Country rank / medal / place fields |
| `inherit_stage` | Sub-stage contest inheritance |
| `detect_major_contests` | Flag major contests (`Promotion`) |
| `calculate_global_rating` | Global rating (uses `elo_mmr_py`) |
| `calculate_problem_rating` | Problem difficulty rating (numpy/numba) |
| `calculate_rating_prediction` | Rating-change prediction |
| `update_auto_rating` | Auto rating update |
| `update_rating_activity` | Rating activity (`Greatest/F/EventStatus`) |
| `anonymize_accounts` | Anonymize accounts |

Every command exposes `--help`. For `parse_statistic` specifically, common flags include
`-r <host>`, `-l <limit>`, `-e <event-regex>`, `-y <year>`, `-u <users>`, `--reparse`,
`--no-update-results`.

To add or fix a management command (CLIST house style + cron/Healthchecks monitor wiring),
follow the [`add-management-command` skill](../.agents/skills/add-management-command/SKILL.md).
