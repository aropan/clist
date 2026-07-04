# AGENTS.md

Short **operating contract** for AI coding agents working in the **CLIST**
repository. It holds only the invariants every agent must see without a click;
everything else lives in [`docs/`](docs/) and in the [skills](#skills).

The per-tool files — `CLAUDE.md`, `GEMINI.md`, and
`.github/copilot-instructions.md` — are symlinks to this file, so Claude,
Gemini, Copilot, Cursor, Codex, and any other agent read the same rules.

> **What CLIST is:** a competitive-programming aggregator — see
> [docs/project-context.md](docs/project-context.md).

---

## Golden rules

- Make **small, reviewable changes**. No large refactors or architectural
  changes unless explicitly asked.
- **Inspect before editing.** Read the relevant files and state a short plan
  before changing code.
- **Match surrounding code** — naming, structure, comment density, imports.
  Prefer existing project patterns over introducing new abstractions or
  dependencies.
- Do not rename public APIs, model fields, DB columns, env vars, or external
  contracts without asking.
- **Never run destructive or outward-facing commands without explicit
  approval**: no `git push`, `git reset --hard`, `git clean -fd`, no `rm -rf`,
  no `DROP`/`DELETE`/`TRUNCATE`, no deploys, no `docker ... prune`.
- Commit or push **only when the user asks**. If on `master`, branch first.
- **Never print or commit secrets** — see
  [docs/git-and-safety.md](docs/git-and-safety.md#off-limits).
- After editing, run the **narrowest relevant check first**, then broaden — see
  [docs/testing.md](docs/testing.md),
  [docs/linting-formatting.md](docs/linting-formatting.md), and the
  [`run-and-verify` skill](#skills).
- Be honest about what was and wasn't verified.

---

## Documentation index

| Doc | Use it for |
|-----|------------|
| [docs/project-context.md](docs/project-context.md) | What CLIST is; the dual Django + legacy PHP codebase |
| [docs/repository-map.md](docs/repository-map.md) | Where things live in `src/`, `legacy/`, `config/`; risk per area |
| [docs/development-environment.md](docs/development-environment.md) | Docker Compose, the long-running `dev` service, `manage.py` commands |
| [docs/testing.md](docs/testing.md) | Django test runner; narrow → broad policy |
| [docs/linting-formatting.md](docs/linting-formatting.md) | Ruff, Biome, type-checking (off) |
| [docs/git-and-safety.md](docs/git-and-safety.md) | Git policy, off-limits files, destructive-command ban |
| [docs/infrastructure.md](docs/infrastructure.md) | Docker services, supervisord, RQ queues, `config/` tree, monitoring |
| [docs/parsers.md](docs/parsers.md) | 1-paragraph overview + pointer to the `add-parser` skill |
| [docs/migrations.md](docs/migrations.md) | 1-paragraph overview + pointer to the `safe-migration` skill |

---

## <a id="skills"></a>Skills

Reusable, step-by-step procedures for recurring tasks are **Agent Skills** —
`SKILL.md` files in `.agents/skills/<name>/` (the cross-tool standard path that
**Codex, Copilot, Gemini CLI, and Antigravity** scan natively; `.claude/skills`
is a symlink to it so **Claude Code** uses the same set). They are discovered
implicitly by description or explicitly via `/skill-name` — nothing to do by
hand. This table just documents what exists.

| Skill | Use it for |
|-------|------------|
| [`add-parser`](.agents/skills/add-parser/SKILL.md) | Add / fix / debug a judge parser in `src/ranking/management/modules/` |
| [`safe-migration`](.agents/skills/safe-migration/SKILL.md) | Any Django schema or data migration |
| [`run-and-verify`](.agents/skills/run-and-verify/SKILL.md) | Pick & run the right narrow checks (tests / lint) after a change |

---

## Expected final response

When you finish a task, summarize:

- **What changed** and **which files**.
- **Checks run** (tests, lint) and their result.
- **Anything not verified** or assumed.
- A suggested next step, if any.
