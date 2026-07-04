# Git policy & safety

← [AGENTS.md](../AGENTS.md)

## Safe git operations (run anytime)

`git status`, `git diff`, `git diff --cached`, `git log --oneline`.

## Operations that need explicit approval

Ask first: `git add`, `git commit`, `git push`, `git reset`, `git checkout`, `git rebase`,
`git clean`. Branch off `master` before committing; never `git reset --hard` or
`git clean -fd` unless explicitly requested.

## Commit style

Loose, but leans **Conventional Commits** (`feat:`, `fix:`, `fix(legacy/db): …`). Keep
the subject short and imperative; reference PR/issue numbers when relevant.

## <a id="off-limits"></a>Off-limits — never print, commit, or expose

- The `.env*` files
- `*_conf` docker secrets (`db_conf`, `sentry_conf`, …)
- Cookies, tokens, API keys
- Anything under `volumes/`
- Anything under `logs/`

## Never run destructive or outward-facing commands

No `git push`, `git reset --hard`, `git clean -fd`, `rm -rf`, `DROP`/`DELETE`/`TRUNCATE`,
deploys, or `docker ... prune` without explicit approval.

## Database changes are high-risk

See [migrations.md](migrations.md). Prefer additive, reversible migrations; never edit
applied historical migrations; never run destructive data migrations without approval.
