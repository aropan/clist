---
name: run-and-verify
description: >-
  Choose and run focused checks after changing CLIST Python code: Django tests,
  standalone pytest tests, offline parser fixtures, Ruff, or a relevant
  management-command check.
---

# Run & verify CLIST changes

The long-running `dev` service hosts Django and RQ. Use it for Django tests and
management commands; run standalone script tests on the host. See
[docs/testing.md](../../../docs/testing.md) for fixtures, CI coverage, and
legacy PHP tests.

## Choose checks by changed behavior

- Django app code: start with a focused test label, then widen only if the
  change affects more code:
  ```bash
  docker compose exec dev ./manage.py test --keepdb ranking.tests.test_parser_regression
  ```
- Parser output: run an existing offline fixture via
  `./manage.py test --keepdb ranking.tests.test_parsers`. Fixture recording
  makes live requests. `parse_statistic --no-update-results` can still write
  contest problems and event logs, so it is not a read-only test.
- Operational Python scripts: run the relevant `src/scripts/tests/` test with
  host pytest. The full standalone command and its pinned dependencies are in
  [docs/testing.md](../../../docs/testing.md#standalone-python-tests).
- Management commands without a focused test: inspect `--help` and choose a
  narrow invocation whose side effects are understood. A flag named
  `--dryrun` is safe only if its implementation actually avoids writes.

Run Ruff on changed Python files from the host:

```bash
mise exec -- ruff check src/path/changed.py
mise exec -- ruff format --check src/path/changed.py
```

Use `ruff format` without `--check` only when intending to change formatting.
Report the exact checks, results, and any behavior they did not cover. When a
check fails, investigate the cause before widening or repeating it.
