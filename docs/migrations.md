# Database & migrations

← [AGENTS.md](../AGENTS.md)

## What & when

Any Django schema or data change: editing models in `src/*/models.py`, creating/running
migrations, adding/renaming/removing model fields or tables, or data migrations. This is
a **high-risk** area — schema drift and destructive data moves are the most common way
to break a shared dev/prod database.

## Highest-risk rules (always)

- Treat schema changes as high-risk and prefer **additive**, **reversible** migrations.
- **Never edit already-applied historical migrations** unless explicitly asked.
- Never run `DROP` / `DELETE` / `TRUNCATE` or irreversible data migrations without
  explicit approval.
- Before a schema change: inspect the model and search the codebase for all usages of
  the field/table; propose the plan before editing.
- Generate migrations with `makemigrations`; never hand-write destructive SQL.

## For the step-by-step playbook

**Read the [`safe-migration` skill](../.agents/skills/safe-migration/SKILL.md)** — it is
the single source of truth for an additive, reversible, non-destructive migration
procedure. See the [skills index in AGENTS.md](../AGENTS.md#skills) for how skills are
discovered.

## Commands

```bash
docker compose exec dev ./manage.py makemigrations <app>     # generate
docker compose exec dev ./manage.py migrate                  # apply
```
