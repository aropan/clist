---
name: safe-migration
description: >-
  Plan, create, or apply CLIST Django schema and data migrations, including
  model field changes, makemigrations, migrate, and RunPython operations.
  Preserve reversibility and check database impact.
---

# Safe Django migrations in CLIST

Database changes are the highest-risk edits in this repo. The DB runs in the
`db` container and holds real data. Be conservative.

## Procedure

1. **Inspect first.** Read the target model in `src/<app>/models.py` and look at
   recent migrations in `src/<app>/migrations/` to match style.
2. **Find all usages** of any field/table you plan to change or remove
   (`rg` across `src/` and `legacy/`). Removing or renaming something
   still referenced will break the app.
3. **Prefer additive changes.** Add new nullable fields rather than renaming or
   dropping. For a rename, prefer add-new → backfill → switch readers → remove
   old, across separate migrations.
4. **Generate schema migrations and review them:**
   ```bash
   docker compose exec dev ./manage.py makemigrations <app>
   docker compose exec dev ./manage.py makemigrations --check --dry-run
   ```
   Data migrations may require a reviewed `RunPython` operation.
5. **Apply only when applying to the target database is part of the task.**
   Confirm the environment and review the generated operations first:
   ```bash
   docker compose exec dev ./manage.py migrate <app>
   ```
6. **Verify** relevant tests and Django checks. If the migration was applied,
   verify the affected app still imports and behaves as expected.

## Hard rules

- **Never edit an already-applied historical migration** unless explicitly
  asked. Add a new one instead.
- **Never** run `DROP` / `DELETE` / `TRUNCATE` or an irreversible data migration
  without explicit user approval.
- Don't rename or drop a column/table without first proving it's unused.
- If a data migration is needed, make it reversible (`RunPython` with a reverse
  function) where feasible, and call out anything that isn't.
- Treat `src/clist/`, `src/true_coders/`, `src/my_oauth/`, `src/ranking/`
  models as high-traffic — extra care.

## When done, report

The migration created, whether it was applied, backward-compatibility risks, and
any manual backfill/cleanup step a human still needs to run.
