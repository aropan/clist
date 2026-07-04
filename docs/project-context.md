# Project context

← [AGENTS.md](../AGENTS.md)

## What CLIST is

CLIST aggregates competitive-programming contests and standings from hundreds of
judges into one place: an upcoming-contest calendar, per-resource leaderboards, unified
coder profiles, ratings, and notifications.

## Two codebases, side by side

- **`src/`** — the **modern app**: **Django 5.1 / Python 3.10+**, served via Docker
  Compose, with Redis + RQ workers and PostgreSQL. This is where almost all new work
  happens.
- **`legacy/`** — the **original PHP application** (Smarty templates, custom DB layer)
  still serving parts of the site in production. Treat it as legacy: change it only when
  a task explicitly targets it, and match the existing PHP style when you do.

## The heart: parsers

The central feature is the **per-judge parsers** under
`src/ranking/management/modules/` (**85 modules**, one per judge). They scrape each
site's contests and standings on a schedule and feed the rating/leaderboard pipeline.
A parallel set of ~100 legacy PHP parsers lives under `legacy/module/<host>/index.php`
— some judges exist in one codebase, some in both.

## Who reads what

- **`README.md`** — onboarding/setup for a **human contributor**.
- **`AGENTS.md`** — short operating contract for **AI coding agents**; it links into
  this `docs/` tree for depth.
- **`.agents/skills/<name>/SKILL.md`** — reusable step-by-step playbooks for recurring
  tasks (parsers, migrations, verification).
