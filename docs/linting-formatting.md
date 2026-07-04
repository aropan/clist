# Linting & formatting

← [AGENTS.md](../AGENTS.md)

## Python — Ruff

Config lives in [`.ruff.toml`](../.ruff.toml).

```bash
ruff check src/path/to/file.py        # lint
ruff format src/path/to/file.py       # format
```

- Line length **120**, double-quoted strings, spaces for indent.
- `*/migrations/*` are excluded; `__init__.py` may keep unused imports.
- Unused imports are **not** auto-removed (`F401` unfixable) — clean them up by hand
  when appropriate.

## JS / CSS / JSON — Biome

Config lives in [`biome.json`](../biome.json): 2-space indent, width 120.

## Type checking — off

Type checking is intentionally **off** ([`pyrightconfig.json`](../pyrightconfig.json)).
Don't add type errors, but don't expect a type gate either.

## Where to run

Run linters from the host using the activated venv (`.envrc` activates the `clist`
virtualenv) or inside the container — both work.
