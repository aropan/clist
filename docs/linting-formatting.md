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

## PHP — PHP-CS-Fixer

Config lives in [`.php-cs-fixer.dist.php`](../.php-cs-fixer.dist.php) and applies
the non-risky `@PER-CS3x0` ruleset plus project readability rules to
project-owned files under `legacy/`. Vendored code in `legacy/libs/` and
Git-ignored runtime files are excluded.

Install the pinned lightweight PHP-CS-Fixer shim once:

```bash
composer install
composer check:php
composer format:php
```

The formatter runs sequentially to avoid CPU spikes. Full-project CLI runs use
the ignored `.php-cs-fixer.cache`; editor formatting still processes only the
current file.

For VS Code, point `junstyle.php-cs-fixer` at
`${workspaceFolder}/vendor/bin/php-cs-fixer` in user settings. Use only
`editor.formatOnSave`; do not also enable `php-cs-fixer.onsave`.

## Type checking — off

Type checking is intentionally **off** ([`pyrightconfig.json`](../pyrightconfig.json)).
Don't add type errors, but don't expect a type gate either.

## Where to run

Run linters from the host using the activated venv (`.envrc` activates the `clist`
virtualenv) or inside the container — both work.
