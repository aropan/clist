# Infrastructure

← [AGENTS.md](../AGENTS.md)

How CLIST is containerized and operated. **High-risk area** — change only with a plan.

## Docker Compose services ([`docker-compose.yml`](../docker-compose.yml))

| Service | Role |
|---------|------|
| `dev` | Local development: `runserver 0.0.0.0:10042` + RQ workers. Long-running. |
| `prod` | Production app, run via supervisord. |
| `db` | PostgreSQL 14.3 (built via the `postgres` Dockerfile stage) |
| `redis` | Cache + RQ broker |
| `pgadmin` | Postgres admin UI |
| `nginx` | Reverse proxy (`nginx:stable-alpine` + crond) |
| `certbot` | TLS certificate renewal |
| `netdata` | System metrics |
| `legacy` | Legacy PHP app (`legacy/Dockerfile`, `php:8-fpm`) served alongside Django |
| `loki`, `promtail`, `grafana` | Log aggregation + dashboards |
| `bugsink` | Self-hosted error tracking (sentry-sdk compatible), DB in `db`; env in `.env.bugsink` |
| `healthchecks` | Self-hosted cron monitoring (pinged by `run-manage.bash`), DB in `db`; env in `.env.healthchecks` |

The app-side error-tracking DSN and Healthchecks ping key live in `.env.monitoring`
(mounted into `prod`/`dev`/`legacy` as the `monitoring_conf` docker secret).

Healthchecks retention, per-check schedule/grace/description and the Telegram alert
channel live in the DB, not in settings. They are pinned as config-as-code in
[`config/healthchecks/provision.py`](../config/healthchecks/provision.py), mounted into
the `healthchecks` container. It is **not** applied automatically — run it by hand
(idempotent) after editing it or after adding a monitored cron:

```
docker compose exec healthchecks sh -c 'python manage.py shell < /opt/healthchecks/provision.py'
```

On failure `run-manage.bash` posts the tail of the command log as the ping body, so the
traceback is visible on the check page (capped by `PING_BODY_LIMIT`).

Static network `10.42.0.x`. `dev` mounts `./src/:/usr/src/clist/`.

## Dockerfile ([`Dockerfile`](../Dockerfile))

Multi-stage: `base` (Python 3.10.11, installs deps via `uv`) → `dev` / `prod` / `nginx`
/ `postgres`. The `dev` stage runs `redis-server`, `watchdog.bash rqworker`, then
`manage.py runserver 0.0.0.0:10042`.

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
| [`config/redis.conf`](../config/redis.conf) | Redis config |
| [`config/ipython_config.py`](../config/ipython_config.py) | Enhanced Django shell |
| [`config/logrotate.conf`](../config/logrotate.conf) | Log rotation |
| [`config/cron`](../config/cron) | crontab triggers for management commands |
| `config/nginx/` | nginx `conf.d/`, `logrotate.d/`, cron |
| `config/postgres/` | `postgresql.conf`, supervisord, cron |
| `config/grafana/` | Grafana provisioning |
| `config/prometheus/` | Metrics config |
| `config/promtail/` | Loki log pipeline |
| `config/loki/` | Loki `local-config.yaml` |

## Legacy image ([`legacy/Dockerfile`](../legacy/Dockerfile))

`php:8-fpm` running `cron && php-fpm` — serves the legacy PHP app alongside the Django
app.
