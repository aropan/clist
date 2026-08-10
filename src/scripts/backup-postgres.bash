#!/usr/bin/env bash

set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
project_dir=$(cd -- "$script_dir/../.." && pwd)
backup_dir=${CLIST_BACKUP_DIR:-/var/backups/clist}

if [[ -L "$backup_dir" ]]; then
  echo "Backup directory must not be a symlink: $backup_dir" >&2
  exit 1
fi

if ! mkdir -p -- "$backup_dir"; then
  echo "Cannot create backup directory: $backup_dir" >&2
  echo "Create it once with suitable ownership, then run this command again." >&2
  exit 1
fi

if ! chmod 700 -- "$backup_dir"; then
  echo "Cannot set mode 0700 on backup directory: $backup_dir" >&2
  exit 1
fi

if [[ ! -d "$backup_dir" || ! -w "$backup_dir" || ! -x "$backup_dir" ]]; then
  echo "Backup directory must be a writable directory: $backup_dir" >&2
  exit 1
fi

backup_dir=$(cd -- "$backup_dir" && pwd -P)
run_options=(--rm --user "$(id -u):$(id -g)")
if [[ ! -t 1 ]]; then
  run_options+=(--no-TTY)
fi

exec env CLIST_BACKUP_DIR="$backup_dir" \
  docker compose --project-directory "$project_dir" --profile tools \
  run "${run_options[@]}" backup "$@"
