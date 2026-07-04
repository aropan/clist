# Repository map

← [AGENTS.md](../AGENTS.md)

Detailed map of where things live and how risky each area is. Treat the **Risk** column
as a routing hint, not a blocker — high-risk areas just warrant a plan before editing.

## `src/` — modern Django app

| Path | What it is | Risk |
|------|------------|------|
| `src/manage.py` | Django entry point (run all management commands through here) | — |
| [`pyclist/`](../src/pyclist/) | Django settings, root URLs, middleware, ASGI/WSGI, shared base model/manager | high |
| [`ranking/`](../src/ranking/) | Heart of the app: `Account`, `Statistics`, `Contest` models + parsers + commands | — |
| `ranking/management/modules/` | **85 per-judge parsers** (+ 2 helpers: `conf.py`, `excepts.py`; `common/`, `external/`) | — |
| `ranking/management/commands/` | `manage.py` commands: parsing, rating, account/statistic linking (16 commands) | — |
| [`clist/`](../src/clist/) | Contests, resources, public API (`clist/api/`), templatetags | high |
| [`true_coders/`](../src/true_coders/) | `Coder`, `User`, countries, profile data | high |
| [`my_oauth/`](../src/my_oauth/) | OAuth layer (Google CLI/server, etc.), service access | high |
| [`events/`](../src/events/) | Event tracking, periodic email reminders | — |
| [`notification/`](../src/notification/) | Subscriptions, calendar, notifications, RQ-queued jobs | — |
| [`favorites/`](../src/favorites/) | Per-user favorite/active data | — |
| [`notes/`](../src/notes/) | User `Note` model | — |
| [`chats/`](../src/chats/) | Real-time chat (`Chat`, `ChatLog`, `ExternalChat`, Daphne WebSocket consumer) | — |
| [`submissions/`](../src/submissions/) | Languages, `Submission`/`SubmissionSource` (rate-limited, cached) | — |
| [`donation/`](../src/donation/) | `DonationSource` (sponsors/streamers) | — |
| [`tg/`](../src/tg/) | Telegram bot (`python-telegram-bot`), group admin | — |
| [`logify/`](../src/logify/) | `EventLog` + `EventStatus` for job-execution monitoring | — |
| [`legacy/`](../src/legacy/) | In-Django proxy bridge to the PHP `legacy/` app | — |
| [`utils/`](../src/utils/) | Shared helpers (~26 modules — `requester/`, `regex`, `timetools`, `aes`, `attrdict`, `parsed_table`, …) | — |
| [`scripts/`](../src/scripts/) | Operational bash/python scripts (watchdog, backups) | high |
| [`templates/`](../src/templates/) | Project-wide Django templates | — |
| [`static/`](../src/static/) | Static assets | — |
| `*/migrations/` | Django migrations per app | **high — see [migrations.md](migrations.md)** |

## Other top-level areas

| Path | What it is | Risk |
|------|------------|------|
| [`legacy/`](../legacy/) | Legacy PHP app + parsers (`legacy/module/<host>/index.php`, ~100 host dirs) | legacy |
| [`config/`](../config/) | Infra config — see [infrastructure.md](infrastructure.md) | high |
| `docker-compose.yml`, `Dockerfile` | Container stack | high |
| `volumes/`, `logs/`, `.env*` | Data, logs, secrets — **[off-limits](git-and-safety.md#off-limits)** | **off-limits** |

Update this table if the real structure drifts.
