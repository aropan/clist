# Database & migrations

← [AGENTS.md](../AGENTS.md)

## What & when

Django schema changes and data migrations: editing model fields in
`src/*/models.py`, creating or applying migrations, and moving stored data.
This is a **high-risk** area because migrations can affect shared databases.

## Highest-risk rules (always)

- Treat schema changes as high-risk and prefer **additive**, **reversible** migrations.
- **Never edit already-applied historical migrations** unless explicitly asked.
- Never run `DROP` / `DELETE` / `TRUNCATE` or irreversible data migrations without
  explicit approval.
- Before a schema change: inspect the model and search the codebase for all usages of
  the field/table; propose the plan before editing.
- Generate schema migrations with `makemigrations` and review them; a data
  migration may need a reviewed `RunPython` operation.

## For the step-by-step playbook

**Read the [`safe-migration` skill](../.agents/skills/safe-migration/SKILL.md)** — it is
the single source of truth for an additive, reversible, non-destructive migration
procedure. See the [skills index in AGENTS.md](../AGENTS.md#skills) for how skills are
discovered.

## Commands

```bash
docker compose exec dev ./manage.py makemigrations <app>        # generate
docker compose exec dev ./manage.py makemigrations --check --dry-run
docker compose exec dev ./manage.py migrate <app>                 # apply when in scope
```
