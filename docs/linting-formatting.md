# Linting & formatting

← [AGENTS.md](../AGENTS.md)

## Tool installation

Formatter versions are pinned in [`mise.toml`](../mise.toml) and
[`mise.lock`](../mise.lock). Install [mise](https://mise.jdx.dev/installing-mise.html)
once, then install all project tools:

```bash
mise install --locked
```

The mise shims are stable entry points that select the version configured by
the nearest `mise.toml`. Different projects can use different versions of the
same formatter on one machine.

## Python — Ruff

Config lives in [`.ruff.toml`](../.ruff.toml).

```bash
mise run lint-python
mise run check-python
mise run format-python
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

```bash
mise run check-php
mise run format-php
```

The formatter runs sequentially to avoid CPU spikes. Full-project CLI runs keep
a checkout-specific cache under `$XDG_CACHE_HOME/clist/php-cs-fixer/`
(`~/.cache/clist/php-cs-fixer/` by default); editor formatting still processes
only the current file.

For VS Code, point both extensions at the mise shims in user settings:

```json
"ruff.path": ["${env:HOME}/.local/share/mise/shims/ruff"],
"php-cs-fixer.executablePath": "~/.local/share/mise/shims/php-cs-fixer"
```

Use only `editor.formatOnSave`; do not also enable `php-cs-fixer.onsave`.

## Type checking — off

Type checking is intentionally **off** ([`pyrightconfig.json`](../pyrightconfig.json)).
Don't add type errors, but don't expect a type gate either.

## Where to run

Run formatter tasks from the host through `mise run`. Application and test
commands can continue using the activated venv (`.envrc` activates the `clist`
virtualenv) or the container.
