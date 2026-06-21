---
name: safe-migration
description: >-
  Use for any Django database schema or data change in CLIST — editing models in
  src/*/models.py, creating/running migrations, adding/renaming/removing model
  fields or tables, or data migrations. Ensures additive, reversible, non-
  destructive changes. Keywords: migration, makemigrations, migrate, schema,
  model field, database, ORM.
---

# Safe Django migrations in CLIST

Database changes are the highest-risk edits in this repo. The DB runs in the
`db` container and holds real data. Be conservative.

## Procedure

1. **Inspect first.** Read the target model in `src/<app>/models.py` and look at
   recent migrations in `src/<app>/migrations/` to match style.
2. **Find all usages** of any field/table you plan to change or remove
   (`grep`/search across `src/` and `legacy/`). Removing or renaming something
   still referenced will break the app.
3. **Prefer additive changes.** Add new nullable fields rather than renaming or
   dropping. For a rename, prefer add-new → backfill → switch readers → remove
   old, across separate migrations.
4. **Generate, don't hand-write:**
   ```bash
   docker compose exec dev ./manage.py makemigrations <app>
   ```
   Review the generated migration file before applying.
5. **Apply:**
   ```bash
   docker compose exec dev ./manage.py migrate <app>
   ```
6. **Verify** the app still imports/serves and relevant tests pass
   (`./manage.py test <app>`).

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
