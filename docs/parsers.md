# Parsers

← [AGENTS.md](../AGENTS.md)

## What & when

Parsers are the most common contribution. Each **per-judge parser** under
[`src/ranking/management/modules/`](../src/ranking/management/modules/) (85 modules)
scrapes one judge's contests and standings and feeds the rating/leaderboard pipeline.
Use this area when adding a new judge, fixing a broken scoreboard scrape, or re-parsing
one contest to test a change.

## For the step-by-step playbook

**Read the [`add-parser` skill](../.agents/skills/add-parser/SKILL.md)** — it is the
single source of truth for the procedure (module structure, the `Statistic.get_standings`
contract, the safe read-only flags to test one contest end-to-end). It is loaded on
demand by Codex / Copilot / Gemini CLI / Antigravity / Claude Code.
See the [skills index in AGENTS.md](../AGENTS.md#skills) for how skills are discovered.

## Legacy PHP parsers

Some judges still have a parser under
[`legacy/module/<host>/index.php`](../legacy/module/) (~100 host dirs). A judge may exist
in one codebase or both; when targeting the legacy one, match the surrounding PHP style.

## Re-parsing a single contest

The narrowest read-only test for a parser change (see the skill for full flag list):

```bash
docker compose exec dev ./manage.py parse_statistic -r <host> -l 1 --no-update-results
```
