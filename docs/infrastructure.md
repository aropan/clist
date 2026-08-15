# Infrastructure

← [AGENTS.md](../AGENTS.md)

How CLIST is containerized and operated. **High-risk area** — change only with a plan.

## Docker Compose services ([`docker-compose.yml`](../docker-compose.yml))

| Service | Role |
|---------|------|
| `dev` | Local development: `runserver 0.0.0.0:10042` + RQ workers. Long-running. |
| `prod` | Production app, run via supervisord. |
| `db` | PostgreSQL 18 plus `pg_repack` 1.5.3 (built via the `postgres` Dockerfile stage) |
| `backup` | On-demand PostgreSQL logical backup tool in the `tools` profile |
| `redis` | Non-persistent shared Django cache; production RQ and Channels use the Redis process inside `prod`, with RDB stored in `./volumes/redis_data` |
| `pgadmin` | Postgres admin UI |
| `nginx` | Reverse proxy (`nginx:stable-alpine` + crond) |
| `certbot` | TLS certificate renewal |
| `netdata` | System metrics |
| `legacy` | Legacy PHP app (`legacy/Dockerfile`, `php:8-fpm`) served alongside Django |
| `loki`, `alloy`, `grafana` | Log collection, aggregation, and dashboards |
| `bugsink` | Self-hosted error tracking (sentry-sdk compatible), DB in `db`; env in `.env.bugsink` |
| `healthchecks` | Self-hosted cron monitoring (pinged by both cron runners), DB in `db`; env in `.env.healthchecks` |

## PostgreSQL backups

The `backup` Compose profile creates an online logical backup of every connectable
non-template database in `db`, plus roles and tablespaces. It does not include Redis,
media/shared files, monitoring data, certificates, `.env` files, or other Docker
volumes.

Production RQ state is stored separately in `volumes/redis_data/dump.rdb`; it is not
part of the PostgreSQL backup. Before maintenance where exact queue state matters,
stop task producers and workers, run `docker compose exec -T prod redis-cli SAVE`,
then snapshot `volumes/redis_data`. This Redis uses RDB without AOF, so a clean
container shutdown is persisted, while a sudden host failure can lose changes since
the most recent snapshot. The separate `redis` service is only a cache and has both
RDB and AOF disabled.

Create the host directory once and build the tool image:

```bash
sudo install -d -m 700 -o "$(id -un)" -g "$(id -gn)" /var/backups/clist
docker compose build backup
```

Run a discovery-only check, then create a backup:

```bash
./src/scripts/backup-postgres.bash --dry-run
./src/scripts/backup-postgres.bash
```

Use `CLIST_BACKUP_DIR=/another/host/path` to override the destination. The defaults
are two parallel workers per database, compression level 6, and retention of verified
backups for seven days. Override them with `--jobs`, `--compression`, and
`--retention-days`; setting retention to `0` disables deletion. A low-space warning
requires an explicit `--allow-low-space` override.

Each completed `postgresql-<UTC>` directory contains `globals.sql`, one compressed
directory-format archive per database, `manifest.json`, and `SHA256SUMS`. Work is
written to a hidden `.in-progress` directory on the same host mount and renamed only
after every archive passes `pg_restore --list` and all checksums are written. The Rich
display shows the current step, database and tables, bytes written, elapsed time, and
an approximate ETA; PostgreSQL does not provide an exact total for `COPY TO`.

Restoration is destructive and should first be tested on a separate empty PostgreSQL
18 cluster. Verify `SHA256SUMS`, stop writers, restore `globals.sql` first, then
restore every database archive listed in `manifest.json` with `pg_restore`. Run
application smoke tests before enabling writers again.

The active cluster is mounted from `volumes/postgres_data`. The previous PostgreSQL
14 cluster is retained outside Compose at `volumes/postgres_data_14` as a recovery
reference. Once PostgreSQL 18 has accepted new writes, PostgreSQL 14 is stale and is
not a direct rollback target without a separate data synchronization step.

The app-side error-tracking DSN and Healthchecks ping key live in `.env.monitoring`
(mounted into `prod`/`dev`/`legacy` as the `monitoring_conf` docker secret).

Healthchecks retention, per-check schedule/grace/description and the Telegram alert
channel live in the DB, not in settings. They are pinned as config-as-code in
[`config/healthchecks/provision.py`](../config/healthchecks/provision.py). The
`config/healthchecks` dir is mounted into the `healthchecks` container at
`/opt/healthchecks/provisioning` (a **directory** mount, so edits are seen live —
a single-file bind pins the host inode and goes stale when an editor replaces the
file). It is **not** applied automatically — run it by hand (idempotent) after
editing it or after adding a monitored cron:

```
docker compose exec healthchecks sh -c 'python manage.py shell < /opt/healthchecks/provisioning/provision.py'
```

Both cron runners — `run-manage.bash` (Django, `config/cron`) and `legacy/update.bash`
(legacy PHP, `legacy/cron`) — share the ping/run logic in
[`src/scripts/healthchecks.bash`](../src/scripts/healthchecks.bash), which the legacy
container gets via a read-only bind mount (`./src/scripts` → `/usr/src/legacy/scripts`).
On failure they post the tail of the command log as the ping body, so the traceback is
visible on the check page (capped by `PING_BODY_LIMIT`).

The Django cron schedules `ensure_telegram_webhook`; see
[`config/cron`](../config/cron) for the current schedule. The command is idempotent
and restores the production webhook when it is missing or points at the URL derived
from an old Telegram token. Run it manually after rotating the token when waiting
for the next cron interval is undesirable.

Google Calendar event synchronization and the separate
`ensure_google_calendars_public` job are also scheduled in
[`config/cron`](../config/cron). The latter keeps the aggregate `CLIST` calendar and
calendars referenced by `Resource.uid` publicly readable without spending ACL quota
on every synchronization pass. New resource calendars are made public immediately.
Use `--dryrun` to audit access without changing Google ACLs.

Static network `10.42.0.x`. `dev` mounts `./src/:/usr/src/clist/`.

## Routine Compose update

Validate the rendered configuration, update the default services, then run the basic
application check:

```bash
docker compose config --quiet
docker compose up --detach --build
docker compose ps
docker compose exec -T prod python manage.py check
```

The `backup` service is not started by this command because it belongs to the `tools`
profile. Check active RQ jobs before intentionally recreating `prod`; interrupted jobs
can be restored from Redis but may need to be requeued if RQ marks them abandoned.

Runtime services follow maintained version channels rather than immutable digests:
Redis, Netdata, pgAdmin and Bugsink follow their current major release; Grafana,
Loki and Healthchecks follow their current minor release; Certbot follows `latest`
because it has no moving major tag. Alloy uses an exact release because its official
image does not publish moving major or minor tags. A routine `up` reuses locally
available images and the build cache. Refresh runtime and base images explicitly,
then recreate affected containers:

```bash
docker compose pull --policy always --ignore-buildable
docker compose build --pull
docker compose up --detach
```

Compose downloads an image automatically when it is missing locally. Images tagged
`latest`, currently Certbot, may also be refreshed by Compose during `up`. The Python
application base remains pinned to its tested patch and digest.

Grafana stores its SQLite database, users, plugins, and unified-storage data in
`grafana_data`. Before a Grafana major upgrade, stop only Grafana and make a cold
copy of that volume. After the Grafana 13 unified-storage migration, rollback also
requires restoring the pre-upgrade volume copy; switching only the image back is
not sufficient.

Alloy reads the nginx access and error logs, preserves the existing Loki labels and
structured metadata, and stores file offsets in `volumes/alloy_data`. On its first
start it imports the legacy Promtail `positions.yaml` from that directory, avoiding
a full replay of existing logs. Its configuration can be validated with the Alloy
service defined in Compose before restarting the monitoring stack.

## Dockerfile ([`Dockerfile`](../Dockerfile))

Multi-stage: `base` (Python 3.14.6, installs locked deps via `uv`) → `dev` / `prod` /
`nginx` / `postgres` / backup tools. The `dev` stage runs `redis-server`,
`watchdog.bash rqworker`, then `manage.py runserver 0.0.0.0:10042`.
Before starting supervisord, the production stage builds static files in an isolated
temporary directory, then publishes them to the shared volume with delayed updates
and deletions. Nginx therefore keeps serving the previous complete set while
`collectstatic` runs and never observes a cleared volume. Static collection is not
performed by individual WSGI or ASGI processes.
Only Font Awesome CSS/webfonts and the runtime Bootswatch/FullCalendar bundles are
included; package metadata, source files, and alternative builds are excluded.
The PostgreSQL stage runs the database and its weekly `pg_repack` cron through
supervisord. Development Redis has snapshots disabled and uses `/tmp` as its working
directory; production Redis persists RQ state in `./volumes/redis_data`.

## Supervisord & RQ queues ([`config/supervisord.conf`](../config/supervisord.conf))

Production runs ASGI (Daphne), uWSGI, cron, redis, logrotate, and **four RQ queues**:
`system`, `default`, `parse_statistics`, `parse_accounts`
(see the `rqworker-*` programs in
[`config/supervisord.conf`](../config/supervisord.conf)).

## `config/` tree

| Path | Purpose |
|------|---------|
| [`config/supervisord.conf`](../config/supervisord.conf) | Prod process supervisor |
| [`config/uwsgi.ini`](../config/uwsgi.ini) | uWSGI config |
| [`config/redis.conf`](../config/redis.conf) | Internal production Redis and RDB config |
| [`config/ipython_config.py`](../config/ipython_config.py) | Enhanced Django shell |
| [`config/logrotate.conf`](../config/logrotate.conf) | Log rotation |
| [`config/cron`](../config/cron) | crontab triggers for management commands |
| `config/nginx/` | nginx `conf.d/`, `logrotate.d/`, cron |
| `config/postgres/` | `postgresql.conf`, supervisord, cron |
| `config/grafana/` | Grafana provisioning |
| `config/alloy/` | nginx-to-Loki log pipeline |
| `config/loki/` | Loki `local-config.yaml` |

## Legacy image ([`legacy/Dockerfile`](../legacy/Dockerfile))

`php:8-fpm` running `cron && php-fpm` — serves the legacy PHP app alongside the Django
app.
