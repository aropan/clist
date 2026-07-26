---
name: run-and-verify
description: >-
  Use after changing CLIST Python code to pick and run the correct, narrowest
  checks — Django tests, Ruff lint/format, or running a management command in
  the dev container — before considering work done. Keywords: test, run tests,
  lint, ruff, verify, check, manage.py, docker compose exec.
---

# Run & verify CLIST changes

The `dev` service is long-running and hosts `runserver` + RQ workers. Run
commands **inside** it; don't start a second server.

## Choose the narrowest check first, then widen

> **Reality check on the test suite:** CLIST's `<app>/tests.py` files are mostly
> stubs (`SimpleTest` doing `assertEqual(1, 1)`). Real coverage is near zero, so a
> green test run is **weak evidence** of correctness. Treat it as a smoke check that
> the app imports and the runner works — **the real verification is running the
> actual management command / RQ job / parser in the dev container** and inspecting
> its output. Add real tests alongside new behavior when feasible.

**Tests** (Django runner; `<app>/tests.py`):
```bash
docker compose exec dev ./manage.py test <app>.tests.SomeTest.test_x   # one test
docker compose exec dev ./manage.py test <app>                          # one app
docker compose exec dev ./manage.py test                                # full suite (broad changes only)
```

**Lint / format** (Ruff, config in `.ruff.toml`, line length 120, double quotes):
```bash
mise exec -- ruff check src/path/you/changed.py
mise exec -- ruff format src/path/you/changed.py
```
Run Ruff from the host through mise. JS/CSS/JSON use Biome (`biome.json`).

**Run a management command** (e.g. to exercise a parser or check a job):
```bash
docker compose exec dev ./manage.py <command>
docker compose exec dev ./manage.py shell      # quick interactive check
```

## Order of operations after an edit

1. Most specific test for the touched module.
2. If it passes, the app's test group.
3. Full suite only when the change is broad.
4. `ruff check` (and `ruff format`) on changed files.
5. Fix root causes, not symptoms. Don't weaken assertions or silence errors to
   make checks pass.

If a check can't run, say exactly why and give the human the command to run.

## When done, report

Which commands ran, their results, what you fixed, and anything left unverified.
