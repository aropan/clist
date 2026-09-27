# Parsers

← [AGENTS.md](../AGENTS.md)

## What & when

**Django standings parsers** under
[`src/ranking/management/modules/`](../src/ranking/management/modules/)
collect results and feed the rating and leaderboard pipeline. Use this area
when adding a standings source or fixing a broken scoreboard scrape.

## For the step-by-step playbook

**Read the [`add-parser` skill](../.agents/skills/add-parser/SKILL.md)** for
the module structure, the `Statistic.get_standings` contract, and safe
verification choices. It is loaded on
demand by Codex / Copilot / Gemini CLI / Antigravity / Claude Code.
See the [skills index in AGENTS.md](../AGENTS.md#skills) for how skills are discovered.

## Legacy PHP parsers

Legacy PHP schedule parsers live under
[`legacy/module/<host>/index.php`](../legacy/module/). A judge may exist in
one codebase or both. For a PHP parser, follow
[`Legacy schedule parser tests`](testing.md#legacy-schedule-parser-tests).

## Checking a parser

Run recorded parser fixtures offline without making network requests or changing
the development database:

```bash
docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parsers
```

To select or record a fixture, see [testing.md](testing.md#parser-regression-tests).
`parse_statistic --no-update-results` is a live command and can still write
contest problems and event logs; use it only when those effects are acceptable.
