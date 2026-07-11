# Testing

← [AGENTS.md](../AGENTS.md)

Tests are Django-style (`<app>/tests.py`), run with the Django test runner inside the
dev container:

```bash
docker compose exec dev ./manage.py test --keepdb ranking                       # one app (narrow — start here)
docker compose exec dev ./manage.py test --keepdb ranking.tests.SomeTest.test_x # one test
docker compose exec dev ./manage.py test --keepdb                               # full suite (broad)
```

Use `--keepdb` for local development. The first run creates the test database and
applies all migrations; later runs preserve it and apply only migrations added since
the previous run. Django's normal test isolation and data cleanup still apply;
`--keepdb` only preserves the database schema between test runs.

After editing an already applied migration in place, or if the test database becomes
inconsistent, run once without `--keepdb` and confirm Django's prompt to recreate it.

When you change code: run the most specific test for the touched module first; if it
passes, widen to the app; run the full suite only for broad changes. If tests can't
run, say exactly why and give the command a human should run.

## Parser regression tests

Parser regression fixtures replay recorded HTTP responses without network access and
compare normalized `get_standings()` output with a golden snapshot:

```bash
docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parsers
```

Fixtures are discovered automatically under `src/ranking/tests/fixtures/parsers/`.
New fixtures are written to `<resource-id>/<contest-id>/` so host or contest-key
renames do not change fixture identity. Each fixture has:

- `db.json` — the `Resource`, `Module`, `Contest`, any directly required
  `ContestSeries`, and the selected `Account`/`Statistics` rows used to limit
  parser replay;
- `httpcache/` — requester response bodies and response metadata;
- `expected_standings.json` or `expected_standings.json.gz` — normalized
  `result`, `problems`, and `options.medals` for the selected users.

A cache miss raises `AssertionError: unexpected network access`, so a passing test is
strictly offline.

The fixture intentionally does not replay every participant. `dump_parser_fixture`
selects saved `Statistics` rows whose `addition` field introduces a new nested key
path, stores those rows in `db.json`, and calls `get_standings(users=...,
statistics=...)` only for those users during record, update, and test replay. The
snapshot does not cover other top-level `options`, `fields`, `hidden_fields`, or
`info`; dictionary insertion order is also normalized away. Response bodies and status
metadata are recorded, but requester cookies are never appended to cached HTML. Failed
HTTP responses are replayable only inside the harness; the production requester keeps
`cache_errors=False`, so transient failures do not become sticky cache entries.

### Record a fixture

Choose a small, completed, standalone contest that is already present in the
development database. Recording performs live requests, immediately replays the new
cache offline, scans the result for credentials, and only then replaces the fixture:

```bash
docker compose exec dev ./manage.py dump_parser_fixture -r codeforces.com -c 1755
docker compose exec dev ./manage.py dump_parser_fixture --resource-id <resource-id> -c 1755
# Equivalent lookup by primary key:
docker compose exec dev ./manage.py dump_parser_fixture --contest-id 38585948
```

After an intentional parser-output change, update only the golden snapshot from the
existing offline cache:

```bash
docker compose exec dev ./manage.py dump_parser_fixture -r codeforces.com -c 1755 --update
```

Review `db.json`, `expected_standings.json`, and the cache diff before committing.
Never add cookies, tokens, API keys, or private standings. Dynamic POST bodies whose
cache key contains a timestamp or nonce may not replay; use a stable
`md5_file_cache` in the parser or leave that parser uncovered until the request can be
made deterministic.

### Audit fixture coverage

List missing parser variants without recording fixtures or making network requests:

```bash
docker compose exec dev ./manage.py dump_parser_fixture --suggest
```

For configured parser-variant resources, the command selects the latest completed,
successfully parsed standalone contest for every observed combination of `kind`,
`standings_kind`, `invisible`, `is_rated`, series being null or non-null, and
`with_medals`. An existing fixture with the same combination counts as covered.

The command also checks the latest contest in each configured annual series. For
these series, the exact latest contest must have a fixture, so a new annual edition is
suggested even when an older edition is already covered.

Record every missing fixture in one batch:

```bash
docker compose exec dev ./manage.py dump_parser_fixture --suggest --update
```

This mode makes live requests and writes fixture files. Every contest still goes
through immediate offline replay and credential checks. An individual failure does
not stop the remaining contests; the command reports all failures and exits with a
non-zero status after the batch.

To refresh suggested fixtures even when the latest candidate is already covered, add
`--force-update`:

```bash
docker compose exec dev ./manage.py dump_parser_fixture --suggest --update --force-update
```

`--suggest` can be combined with `--resource`, `--resource-id`, `--contest-key`, or
`--contest-id` to audit or update only a subset of candidates.

Use Django's built-in verbosity flag when a recording failure is unclear:

```bash
docker compose exec dev ./manage.py dump_parser_fixture --suggest -r nerc.itmo.ru/school --update --verbosity 2
```

`--verbosity 2` prints the main recording phases for each fixture; `--verbosity 3`
also prints temporary paths, standings keys, and cache-file counts.

The same offline test command is suitable for application CI. The current GitHub
workflow only runs CodeQL and does not provision the Django/PostgreSQL environment,
so parser tests are not attached to that workflow.
