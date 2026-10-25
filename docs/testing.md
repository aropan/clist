# Testing

← [AGENTS.md](../AGENTS.md)

Django tests live in `src/<app>/tests.py` and `src/<app>/tests/`. Run them with
the Django test runner inside the dev container:

```bash
docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parser_regression # focused module
docker compose exec dev ./manage.py test --keepdb ranking                              # one app
docker compose exec dev ./manage.py test --keepdb                                      # full suite
```

Use `--keepdb` for local development. The first run creates the test database and
applies all migrations; later runs preserve it and apply only migrations added since
the previous run. Django's normal test isolation and data cleanup still apply;
`--keepdb` only preserves the database schema between test runs.

Do not edit an already applied migration to repair a test database. If its schema
becomes inconsistent, review the target and recreate only the test database by
running once without `--keepdb`.

When you change code: run the most specific test for the touched module first; if it
passes, widen to the app; run the full suite only for broad changes. If tests can't
run, say exactly why and give the command a human should run.

The project test runner has two opt-in guards. The CI command below enables both:

```bash
docker compose exec dev ./manage.py test --keepdb --require-tests utils.tests  # fail on empty labels
docker compose exec dev ./manage.py test --keepdb --deny-network                # fail on outbound access
```

- `--require-tests` fails before running anything when any label, or the whole
  selection after `--tag`/`-k` filtering, contains no tests. A typo in a label or
  an emptied module therefore cannot pass as "0 tests".
- `--deny-network` installs a Python audit hook. Host lookups and TCP connections to
  anything except loopback, the container's own hostname, and the hosts configured in
  `DATABASES`, `CACHES`, `RQ_QUEUES`, and `CHANNEL_LAYERS` raise
  `NetworkAccessDenied`, as do `curl`/`wget` subprocesses. Every attempt is listed
  after the run with the test that made it and fails the run, even when application
  code swallows the exception. Mock the code that makes the request; for example,
  patch `Resource.update_icon` when a test creates a `Resource` without `icon_file`.
  The hook sees Python code only (libpq connections never reach it). It cannot be
  combined with `--parallel`: workers start without the hook, so the runner rejects
  that combination before running anything.

## Standalone Python tests

The tests under `src/scripts/tests/` run directly with pytest, without Django
or the application database. This is the command used by the CI workflow:

```bash
uv run --no-project --python 3.14 --with pytest==9.1.1 --with rich==15.0.0 --with google-auth-oauthlib==1.4.0 pytest -q src/scripts/tests
```

## CI application tests

The `Django tests` job in `.github/workflows/ci.yml` runs the Django checks and the
full Django suite in an isolated stack. Reproduce it locally with the same command:

```bash
mise run test-django
```

The parser fixture archives must be fetched from Git LFS first
(`git lfs pull --include="src/ranking/tests/fixtures/parsers/**"`). The command checks
this before building anything and lists any missing or pointer files together with
the fetch command.

`src/scripts/test-django.bash` builds and runs `docker-compose.test.yml` as the
separate Compose project `clist-test`, passed as `--project-name` so that a
`COMPOSE_PROJECT_NAME` in the environment cannot redirect it to another stack:

- `db` is a disposable PostgreSQL built from the `postgres-base` stage of `Dockerfile`,
  the same pinned image as the project database, with data on tmpfs and no published
  ports;
- `redis` is a disposable cache; the `tests` container also starts its own local
  `redis-server`, as the `dev` image does;
- `tests` is the `dev` image built from `uv.lock`. Like `dev`, it mounts `src/` and
  `legacy/api/`, the latter read-only for the Google Calendar ACL code. It reads only
  the synthetic configuration in `config/test/`: `conf.py` is mounted over
  `pyclist/conf.py`, `parser_conf.py` over the parser credentials in
  `ranking/management/modules/conf.py`, and `DJANGO_ENV_FILE`, `DJANGO_DB_CONF`, and
  `DJANGO_MONITORING_CONF` point to the `config/test/*.env` files. `logs/`,
  `mediafiles/`, and `sharedfiles/` are empty tmpfs mounts. Runtime files that a
  parser needs on construction get synthetic stand-ins from `config/test/sharedfiles/`.
  Local `.env.*` files, `/run/secrets`, the real `pyclist/conf.py` and parser
  `conf.py`, and the shared files of the `clist` stack are not read.

All three services share an internal network with no internet access. Inside the
container the command runs, in order:

1. `manage.py check --fail-level WARNING`;
2. `manage.py makemigrations --check --dry-run`;
3. `manage.py test --noinput --timing --require-tests --deny-network` with the label
   `.` (the full suite) plus explicit labels for the critical suites: OAuth,
   account binding, notifications, Telegram, and the parser replay with its harness.
   The explicit labels make a removed or emptied critical module fail the run; tests
   selected twice run once. There is no `--keepdb`, so the test database is created by
   applying every migration to an empty database.

The command removes the stack (`down --volumes --remove-orphans`) before and after
every run, including failed runs, and exits with the job's status. Before each removal
it lists the containers labelled with the `clist-test` project. If any of them was not
created from this checkout's `docker-compose.test.yml`, it names them and stops without
removing anything. If the stack cannot be removed after the run, the command fails even
when the tests passed. It never touches the `clist` stack, its database, cache, or volumes;
only the built images stay cached.
In a checkout without `src/pyclist/conf.py` or `src/ranking/management/modules/conf.py`,
such as a CI runner, Docker creates an empty, root-owned placeholder at that path for
the bind mount; both paths are gitignored.

## Parser regression tests

Parser regression fixtures replay recorded HTTP responses without network access and
compare normalized `get_standings()` output with a golden snapshot:

The compressed fixtures use Git LFS. If the checkout contains pointer files,
fetch their contents before running these tests:

```bash
git lfs pull --include="src/ranking/tests/fixtures/parsers/**"
```

`ParserFixtureInventoryTests` guards the fixture set itself. It fails, listing each
problem with the fetch command above, when the fixture root has no `db.json`, a
fixture lacks `httpcache.json.gz` or `expected_standings.json[.gz]`, a `.gz` file
is still a Git LFS pointer (`... Git LFS pointer instead of archive data`), or a
`.gz` file is not gzip data. An incomplete or unfetched fixture therefore fails
instead of being silently skipped by discovery.
It also rejects a missing `meta.json` or a `recorded_at` value without a valid timezone.

```bash
docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parsers
```

Fixtures are discovered automatically under `src/ranking/tests/fixtures/parsers/`.
New fixtures are written to `<encoded-host>/<contest-id>/`. The host stays readable,
while `/` is encoded as `__` and a literal `_` as `%5F`, so every resource occupies
one directory (`nerc.itmo.ru/school` becomes `nerc.itmo.ru__school`). Each fixture has:

- `db.json` — the `Resource`, `Module`, `Contest`, any directly required
  `ContestSeries`, and the selected `Account`/`Statistics` rows used to limit
  parser replay;
- `meta.json` — the timezone-aware `recorded_at` used as the fixed replay time;
- `httpcache.json.gz` — one deterministic archive containing requester response
  bodies and response metadata;
- `expected_standings.json` or `expected_standings.json.gz` — normalized
  `result`, `problems`, and `options.medals` for the selected users.

A cache miss raises `AssertionError: unexpected network access`, so a passing test is
strictly offline. Offline replay also skips requester proxy setup, so a parser that
enables proxies never loads or fetches a proxy list.

Offline replay freezes Python's wall clock at the time saved in `meta.json`, so
date-dependent parser behavior stays consistent across test runs. The clock is
restored after each replay, including when parsing fails. Database-server clocks
and external processes are not frozen.

New recordings save their start time and use it for both immediate offline checks.
Live requests use real time so authentication timestamps and network operations keep
working. `--update` preserves the saved time when replaying the existing cache.

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

Review `db.json`, `expected_standings.json`, and the decompressed
`httpcache.json.gz` diff before committing.
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

The GitHub CI workflow has two jobs. `Checks` runs the full Ruff lint check, the
Python/frontend/PHP formatting checks, and all standalone script tests on Python 3.14.
Once `Checks` passes, `Django tests` runs `mise run test-django` (see
[CI application tests](#ci-application-tests)), which replays every parser fixture
together with the rest of the Django suite. A separate CodeQL workflow analyzes Python
and JavaScript.

CI does not cover:

- the legacy PHP offline harness (`legacy/tests/`);
- the `prod` image and the production settings branch (`DEBUG=False`, Sentry);
- RQ workers, a real Channels Redis layer, and GeoIP-dependent code (no GeoLite
  database);
- frontend JavaScript;
- live fixture recording, which needs network access by design.

## Legacy schedule parser tests

The legacy resource filter also has offline tests covering request/cookie input,
bound SQL parameters, and the database wrapper without network or database access:

```bash
docker compose exec -T legacy php tests/test_resource_filter.php
```

Contest schedule parsing lives in legacy PHP (`legacy/module/<host>/index.php`,
driven by `legacy/update.php`). Offline regression fixtures replay recorded HTTP
responses against a single module and diff its normalized raw `$contests[]` output
with a golden snapshot. PHP exists only in the `legacy` container:

```bash
docker compose exec legacy php tests/run.php              # replay all fixtures
docker compose exec legacy php tests/run.php atcoder.jp   # one fixture
docker compose exec legacy php tests/test_harness.php     # fixture infrastructure checks
```

Fixtures live in `legacy/tests/fixtures/<encoded-host>/`, using the same host encoding
as standings fixtures (`/` becomes `__`, while a literal `_` becomes `%5F`):

- `meta.json` — resolved resource globals (`rid`, `path`, `parse_url` with the raw
  `${YEAR}` placeholder, timezone, info) plus `recorded_at`;
- `httpcache.json.gz` — one deterministic Git LFS archive containing every raw
  response and its metadata (`method`, `url`, `effective_url`,
  `response_code`), keyed by HTTP method + URL + postfields, so HEAD and
  POST/GraphQL parsers replay too;
- `expected_contests.json` — normalized golden snapshot (plain JSON, reviewable).

Replay is strictly offline: URL stream wrappers are disabled, schedule modules are
rejected if they call raw network functions instead of `curlexec()`, and a cache miss
is a fatal `curlexec replay miss` error. The runner also fails when there are no
fixtures, so an empty suite cannot produce a false green result.
Each fixture runs in its own subprocess wrapped in `faketime <recorded_at>` so
modules that infer the year from the current date stay deterministic. Missing
`faketime` is a fatal configuration error rather than a fallback to the live clock;
rebuild the legacy image in that case. Re-record a fixture when its module or the
site intentionally changes:

```bash
docker compose exec legacy php tests/record.php leetcode.com [--parse-full-list]
```

Recording performs live requests, needs DB access for the resource row, refuses
0-contest output, and automatically retries with `parse_full_list` when the normal
schedule view is empty. It scans metadata, golden output, response bodies, and
response metadata for credential fields and known secret environment values, then
immediately replays offline before replacing the fixture. A narrowly scoped public technical
field can be allowed in `meta.json` with
`allowed_sensitive_fields: [{"file": "httpcache/...", "path": "$.path.to.field"}]`;
never allow an actual credential. Recorded `Set-Cookie` values and URL userinfo are
replaced with explicit redaction placeholders before validation and storage.

Add or refresh a deterministic offline fixture whenever a PHP schedule module is
introduced or its output intentionally changes. Prefer public schedule responses
that can be recorded without credentials, and use the recorder's full-list fallback
when the normal schedule view is empty. Treat `legacy/tests/fixtures/` and the test
runner output as the source of truth for current coverage instead of maintaining a
resource-specific inventory here.

Limitations: regexp-only resources (`clist_resource.regexp`, parsed inline in
`update.php`) are not covered; two identical requests in one run replay the same
response.

## Schedule parsing breakage detection

`legacy/update.php` writes per-resource stats (`n_contests_parsed`,
`n_contests_upserted`, `elapsed`) to `legacy/logs/update_stats.json` on every full
run. The `check_schedule_parsing` management command (cron, every 15 minutes) reads
it and alerts via Telegram admin message + `EventLog` when the run is stale, a
resource that recently produced contests now parses zero, or parsed contests stop
being upserted. Test it against a synthetic stats file:

```bash
docker compose exec dev ./manage.py check_schedule_parsing --stats-file <path> --dryrun
```
