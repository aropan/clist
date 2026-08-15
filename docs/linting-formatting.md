# Linting & formatting

← [AGENTS.md](../AGENTS.md)

## Tool installation

Host tool versions are pinned in [`mise.toml`](../mise.toml) and
[`mise.lock`](../mise.lock). Install [mise](https://mise.jdx.dev/installing-mise.html)
once, then trust the project configuration and install all project tools:

```bash
mise trust
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

```bash
mise run check-frontend
mise run format-frontend
```

Biome formats project-owned JavaScript and CSS under `src/static/` plus root
JSON configuration files. Vendored libraries, generated localization files,
and minified assets are excluded. Linting remains disabled until the legacy
frontend rules and globals are migrated separately.

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

Shared VS Code formatter selection and format-on-save settings live in
[`.vscode/settings.json`](../.vscode/settings.json). The extension recommendations
are optional and do not affect other editors.

Because this is a uv project, mise creates `.venv` with Python 3.14 as required by
[`uv.lock`](../uv.lock) when it is missing and activates it when entering the project
when mise shell activation is enabled. Run `mise exec -- uv sync --locked` if you need
the application dependencies on the host; the Docker workflow does not require a host
virtualenv.
The shared workspace settings disable legacy Python extension activation. Keep
executable paths and the current Python Environments activation setting in VS
Code user settings because they are machine-specific:

```json
{
  "python-envs.terminal.autoActivationType": "off",
  "ruff.path": ["${env:HOME}/.local/share/mise/shims/ruff"],
  "php-cs-fixer.executablePath": "~/.local/share/mise/shims/php-cs-fixer",
  "biome.lsp.bin": "/home/your-user/.local/share/mise/shims/biome"
}
```

`python-envs.terminal.autoActivationType` has machine scope, so VS Code ignores
it in workspace settings. The Biome extension requires an absolute binary path
and does not expand `~` or `${env:HOME}`.

Use only `editor.formatOnSave`; do not also enable `php-cs-fixer.onsave`.

## Where to run

Run formatter tasks from the host through `mise run`. Application and test
commands can continue using the project virtualenv activated by mise or the
container.
