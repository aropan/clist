# Testing

← [AGENTS.md](../AGENTS.md)

Tests are Django-style (`<app>/tests.py`), run with the Django test runner inside the
dev container:

```bash
docker compose exec dev ./manage.py test ranking                              # one app (narrow — start here)
docker compose exec dev ./manage.py test ranking.tests.SomeTest.test_x        # one test
docker compose exec dev ./manage.py test                                      # full suite (broad)
```

When you change code: run the most specific test for the touched module first; if it
passes, widen to the app; run the full suite only for broad changes. If tests can't
run, say exactly why and give the command a human should run.
