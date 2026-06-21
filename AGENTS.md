# AGENTS.md

Operating contract for AI coding agents working in the **CLIST** repository.
This file is the primary source of truth for *how* to work here. It is
tool-agnostic on purpose: `CLAUDE.md`, `GEMINI.md`, and
`.github/copilot-instructions.md` are symlinks to this file so Claude, Gemini,
Copilot, Cursor, Codex, and any other agent read the same rules.

Keep this file short. It holds **invariants** (the map). Long procedures and
reference material belong in `docs/`, in module docstrings, or alongside the
code they describe — link to them from here instead of inlining them.

---

## Project overview

CLIST aggregates competitive-programming contests and standings from ~hundreds
of judges. Two codebases live side by side:

- **`src/`** — the modern app: **Django 5.1 / Python 3.10+**, served via Docker
  Compose, with Redis + RQ workers and PostgreSQL.
- **`legacy/`** — the original **PHP** application (Smarty templates, custom DB
  layer) still serving parts of the site. Treat it as legacy: change only when a
  task explicitly targets it, and match the existing PHP style.

The heart of the project is the **parsers** under
`src/ranking/management/modules/` (88+ modules), each scraping one judge.

---

## Golden rules

- Make **small, reviewable changes**. Do not do large refactors or
  architectural changes unless explicitly asked.
- **Inspect before editing.** Read the relevant files and state a short plan
  before changing code.
- **Match surrounding code** — naming, structure, comment density, imports.
  Prefer existing project patterns over introducing new abstractions or
  dependencies.
- Do not rename public APIs, model fields, DB columns, env vars, or external
  contracts without asking.
- **Never run destructive or outward-facing commands without explicit
  approval**: no `git push`, `git reset --hard`, `git clean -fd`, no `rm -rf`,
  no `DROP`/`DELETE`/`TRUNCATE`, no deploys, no `docker ... prune`.
- Commit or push **only when the user asks**. If on `master`, branch first.
- **Never print or commit secrets**: the `.env*` files, `*_conf` docker
  secrets, cookies, tokens, API keys, or anything under `volumes/`.
- After editing, run the **narrowest relevant check first**, then broaden.
- Be honest about what was and wasn't verified.

---

## Repository map

| Path | What it is | Risk |
|------|------------|------|
| `src/` | Django project (`manage.py` lives here) | — |
| `src/pyclist/` | Django settings, URLs, middleware, core config | high |
| `src/ranking/management/modules/` | Per-judge parsers (88+) | — |
| `src/ranking/management/commands/` | `manage.py` commands (parsing, rating) | — |
| `src/clist/` | Contests, resources, public API (`clist/api/`) | high |
| `src/true_coders/`, `src/my_oauth/` | Users, auth, OAuth | high |
| `src/*/migrations/` | Django migrations | **high — see below** |
| `src/utils/` | Shared helpers (`requester`, `regex`, `timetools`, …) | — |
| `src/scripts/` | Operational bash/python scripts | high |
| `legacy/` | Legacy PHP app + parsers (`legacy/module/<host>/`) | legacy |
| `config/`, `docker-compose.yml`, `Dockerfile` | Infra | high |
| `volumes/`, `logs/`, `.env*` | Data, logs, secrets — **do not touch/commit** | **off-limits** |

Update this table if the real structure drifts.

---

## Running things

The app runs in Docker Compose. The **`dev` service is long-running** (it hosts
`runserver` + RQ workers). Run Django management commands *inside* it — don't
start a second server.

```bash
# Run any management command in the running dev container:
docker compose exec dev ./manage.py <command>

# Start the dev stack (only if it isn't already up):
docker compose up dev

# App: http://localhost:10042/  (see README.md for first-time setup via configure.py)
```

Useful commands:

```bash
docker compose exec dev ./manage.py shell        # Django shell
docker compose exec dev ./manage.py migrate
docker compose exec dev ./manage.py makemigrations <app>
```

Do not start long-running services without saying what will run and why.

---

## Testing policy

Tests are Django-style (`<app>/tests.py`), run with the Django test runner
inside the dev container:

```bash
docker compose exec dev ./manage.py test ranking         # one app (narrow — start here)
docker compose exec dev ./manage.py test ranking.tests.SomeTest.test_x   # one test
docker compose exec dev ./manage.py test                 # full suite (broad)
```

When you change code: run the most specific test for the touched module first;
if it passes, widen to the app; run the full suite only for broad changes. If
tests can't run, say exactly why and give the command a human should run.

---

## Linting & formatting

Python is linted/formatted with **Ruff** (config in `.ruff.toml`):

```bash
ruff check src/path/to/file.py        # lint
ruff format src/path/to/file.py       # format
```

- Line length **120**, double-quoted strings, spaces for indent.
- `*/migrations/*` are excluded; `__init__.py` may keep unused imports.
- Unused imports are **not** auto-removed (`F401` unfixable) — clean them up by
  hand when appropriate.
- JS/CSS/JSON formatting uses **Biome** (`biome.json`): 2-space indent, width 120.
- Type checking is intentionally **off** (`pyrightconfig.json`); don't add type
  errors but don't expect a type gate either.

Run linters from the host using the activated venv (`.envrc` activates the
`clist` virtualenv) or inside the container — both work.

---

## Adding or editing a parser

Parsers are the most common contribution. To add a judge:

1. Read 2–3 existing modules in `src/ranking/management/modules/` that scrape a
   similar site — copy their structure and conventions.
2. Implement the `Statistic` class subclassing the base module; use
   `src/utils/requester` for HTTP and `src/utils/regex` / `timetools` helpers
   rather than re-rolling them.
3. Test a single contest end-to-end without writing junk data — prefer narrow,
   read-only flags:

   ```bash
   docker compose exec dev ./manage.py parse_statistic -r <host> -l 1 --no-update-results
   ```

   (`parse_statistic --help` lists all flags: `-e` event regex, `-y` year,
   `-u` users, `--reparse`, etc.)
4. Legacy PHP parsers live under `legacy/module/<host>/index.php` — a judge may
   exist in one codebase or both.

---

## Skills (task playbooks)

Reusable, step-by-step procedures for recurring tasks are **Agent Skills** —
`SKILL.md` files in the open, portable format. Canonical location is
`.agents/skills/<name>/SKILL.md`, the cross-tool standard path that **Codex,
Copilot, Gemini CLI, and Antigravity scan and load natively** (name + description
up front, full body only when a skill is selected — implicit by description or
explicit via `/skill-name`). `.claude/skills` is a symlink to `.agents/skills` so
**Claude Code** picks up the same skills from its native path. One source, every
agent.

There is nothing to do "by hand" — if your agent supports skills, it discovers
these automatically; this index just documents what exists.

| Skill | Use it for |
|-------|------------|
| [`add-parser`](.agents/skills/add-parser/SKILL.md) | Add / fix / debug a judge parser in `src/ranking/management/modules/` |
| [`safe-migration`](.agents/skills/safe-migration/SKILL.md) | Any Django schema or data migration |
| [`run-and-verify`](.agents/skills/run-and-verify/SKILL.md) | Pick & run the right narrow checks (tests / lint) after a change |

---

## Database & migrations (high-risk)

- Treat schema changes as high-risk and prefer **additive** migrations.
- **Never edit already-applied historical migrations** unless explicitly asked.
- Before a schema change: inspect the model and search the codebase for all
  usages of the field/table; propose the plan before editing.
- Generate migrations with `makemigrations`; never hand-write destructive SQL.
- Never run `DROP` / `DELETE` / `TRUNCATE` or irreversible data migrations
  without explicit approval.

---

## Git policy

Safe to run anytime: `git status`, `git diff`, `git diff --cached`,
`git log --oneline`.

Ask first: `git add`, `git commit`, `git push`, `git reset`, `git checkout`,
`git rebase`, `git clean`. Branch off `master` before committing; never
`git reset --hard` or `git clean -fd` unless explicitly requested.

Commit message style in this repo is loose but leans
**Conventional Commits** (`feat:`, `fix:`, `fix(legacy/db): …`). Keep the
subject short and imperative; reference PR/issue numbers when relevant.

---

## Expected final response

When you finish a task, summarize:

- **What changed** and **which files**.
- **Checks run** (tests, lint) and their result.
- **Anything not verified** or assumed.
- A suggested next step, if any.
