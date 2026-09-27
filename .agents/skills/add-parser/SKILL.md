---
name: add-parser
description: >-
  Add, fix, or debug a Django standings parser in
  src/ranking/management/modules/, including Statistic.get_standings,
  leaderboard scraping, and offline regression fixtures. Excludes legacy PHP
  schedule parsers.
---

# Add or fix a CLIST parser

Judge parsers live in `src/ranking/management/modules/`. Most expose a
`Statistic` class that subclasses `BaseModule`; some extend another parser.
Read two similar modules before editing.

## The contract

Implement `Statistic.get_standings(self, users=None, statistics=None, **kwargs)`
using the contest metadata on `self` (`url`, `key`, `info`,
`standings_url`, `resource`). Return site-specific standings in the shape
below. Use a similar existing module for the request and row mapping; there
is no shared response schema across judges.

### Return shape

`get_standings` returns a dict with at least `result`: a mapping of
`member -> row`. Common row keys:

- `member` (**required**, str) — stable per-user handle/id.
- `place`, `solving`, `name`.
- `problems` — `{short: {'result': '+', 'time': '01:23', ...}}` per-problem.
- `info` — extra per-row data (avatar, rating, country…).

Optional dict keys alongside `result`: `problems` (contest problem list),
`url`, `options`, `hidden_fields`, `season`.

### Rules of the road

- Use `REQ` (`from ...common import REQ`) for HTTP — never raw `requests`. It
  handles cookies, proxies, retries. `REQ.get(url, post=..., return_json=True,
  headers=...)`.
- Reuse helpers in `src/utils/`: `regex`, `timetools`, and
  `clist.templatetags.extras.get_item` for safe nested lookups.
- Raise `ExceptionParseStandings` (from `.excepts`) on bad/unexpected responses,
  not bare `Exception`.
- Keep it minimal and match the style of neighboring modules. Don't add new
  dependencies.
- Optional methods only if needed: `get_users_infos(users, resource, accounts,
  pbar)` (profile/rating data), `get_source_code(contest, problem)`.

Good clean references to read: `highload.py`, `algorithm_yandex.py`,
`codeforces_gym.py`. For HTML scraping (not JSON) look at modules using
`REQ.get(...)` + parsing.

## Verification

Run a relevant recorded fixture offline when one exists:

```bash
docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parsers
```

See [parser regression tests](../../../docs/testing.md#parser-regression-tests)
for fixture selection and recording. Recording makes live requests and writes
fixture files. `parse_statistic` also makes live requests and can write to the
development database even with `--no-update-results` (contest problems and
event logs). Use it only when the task calls for a live parse and those effects
are acceptable; consult `./manage.py parse_statistic --help` for current flags.

## Wiring a brand-new judge

A parser file alone isn't enough for a *new* site: a `Resource` + its `Module`
(`Module.path = ranking.management.modules.<host>`) must exist in the DB. If the
resource already exists, just edit/add the `.py`. If it's a new resource, say so
and confirm how the resource row should be created before assuming.

## When done, report

Module changed, fixture/test commands and results, and whether any live
requests or database writes were performed.
