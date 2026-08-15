# CLIST

> CLIST aggregates competitive-programming contests and standings from hundreds of
> judges into one calendar, with per-resource leaderboards, unified coder profiles, and
> ratings. See [`docs/project-context.md`](docs/project-context.md) for the full
> overview (modern Django app + legacy PHP app).

## Prerequisites

- [Python 3.14](https://www.python.org/downloads/)
- [Docker (with Docker Compose v2)](https://www.docker.com/products/docker-desktop)
- Optional: [mise](https://mise.jdx.dev/installing-mise.html) for pinned host tools
  and a local Python virtualenv

## Development setup

```bash
# 1. Fork on GitHub, then clone your fork (submodules included):
git clone --recursive https://github.com/<your-username>/clist.git
cd clist

# 2. Optional, when mise is installed: trust the project config and install tools.
#    Mise then creates .venv with the required Python version when needed.
mise trust
mise install --locked

# 3. Generate default environment files (press Enter to accept defaults):
python3 ./configure.py

# 4. Build and start the long-running dev container:
docker compose up --build dev

# 5. Open the app:
#    http://localhost:10042/
```

Skip step 2 if you do not use mise; the Docker development setup does not depend
on it. See [`docs/linting-formatting.md`](docs/linting-formatting.md) for the host
tooling and local virtualenv workflow.

## Going further

| Want to… | Read |
|----------|------|
| Run management commands, get a Django shell | [`docs/development-environment.md`](docs/development-environment.md) |
| Find where something lives / what's risky to touch | [`docs/repository-map.md`](docs/repository-map.md) |
| Run tests, lint, format | [`docs/testing.md`](docs/testing.md), [`docs/linting-formatting.md`](docs/linting-formatting.md) |
| Add or fix a judge parser | [`docs/parsers.md`](docs/parsers.md) + the `add-parser` skill |
| Change the DB schema | [`docs/migrations.md`](docs/migrations.md) + the `safe-migration` skill |
| Understand the production stack | [`docs/infrastructure.md`](docs/infrastructure.md) |

For repeated local test runs, preserve the migrated test database:

```bash
docker compose exec dev ./manage.py test --keepdb
```

The first run creates and migrates the test database; later runs reuse it and apply
only new migrations. See [`docs/testing.md`](docs/testing.md) for narrower test
commands.

**AI coding agents** start in [`AGENTS.md`](AGENTS.md) — the short operating contract
that links into the same `docs/` tree.

## Contributing

1. Branch off `master`: `git checkout -b my-new-feature`
2. Commit, push, and open a Pull Request.

For the detailed git policy and safety rules, see
[`docs/git-and-safety.md`](docs/git-and-safety.md).
