---
name: add-parser
description: >-
  Use when adding, fixing, or debugging a CLIST contest/standings parser — any
  task involving a judge scraper in src/ranking/management/modules/, the
  Statistic.get_standings contract, scraping a new site's leaderboard, or
  re-parsing one contest to test scraping. Keywords: parser, scraper, module,
  standings, judge, resource, get_standings.
---

# Add or fix a CLIST parser

Each judge is one module in `src/ranking/management/modules/<host>.py` exposing a
`Statistic` class that subclasses `BaseModule`. There are 88+ existing modules —
**always read 2–3 similar ones first and copy their conventions.**

## The contract

```python
from ranking.management.modules.common import REQ, BaseModule
from ranking.management.modules.excepts import ExceptionParseStandings


class Statistic(BaseModule):
    def get_standings(self, users=None, statistics=None, **kwargs):
        # Contest metadata is on self: self.url, self.key, self.info,
        # self.start_time, self.standings_url, self.resource, ...
        data = REQ.get(self.standings_url, return_json=True)   # or post=..., headers=...
        if not_ok(data):
            raise ExceptionParseStandings(data)

        result = {}
        for row_data in data['rows']:
            member = str(row_data['user_id'])          # stable unique handle
            row = result.setdefault(member, {'member': member})
            row['name'] = row_data['user_name']
            row['solving'] = row_data['score']          # number of solved / score
            row['place'] = row_data['rank']
            row.setdefault('info', {})['avatar'] = row_data.get('avatar')
        return {'result': result}
```

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

## Test loop (safe, narrow, no junk data)

The `dev` container is already running. Re-parse a single contest read-only:

```bash
docker compose exec dev ./manage.py parse_statistic -r <host> -l 1 --no-update-results -s
```

- `-r <host>` resource host (e.g. `highload.io`)   `-l 1` only one contest
- `--no-update-results` don't write results   `-s` stop on first exception
- Narrow further: `-e "<event regex>"`, `-y <year>`, `-u <user>`, `--reparse`
- `parse_statistic --help` lists every flag.

Iterate until the standings parse cleanly, then drop `--no-update-results` for a
real run only if the task calls for it.

## Wiring a brand-new judge

A parser file alone isn't enough for a *new* site: a `Resource` + its `Module`
(`Module.path = ranking.management.modules.<host>`) must exist in the DB. If the
resource already exists, just edit/add the `.py`. If it's a new resource, say so
and confirm how the resource row should be created before assuming.

## When done, report

Module changed, how you tested (the exact `parse_statistic` command + result),
and whether real results were written or only dry-run.
