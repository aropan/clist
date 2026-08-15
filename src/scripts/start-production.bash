#!/usr/bin/env bash

set -euo pipefail

bash "$APPDIR/scripts/wait-for-postgres.bash"

static_build_dir="$(mktemp -d /tmp/clist-static.XXXXXX)"
trap 'rm -rf -- "$static_build_dir"' EXIT

STATIC_ROOT="$static_build_dir" python manage.py collectstatic --noinput
chmod 755 "$static_build_dir"
mkdir -p "$APPDIR/staticfiles"
rsync --archive --delay-updates --delete-delay "$static_build_dir/" "$APPDIR/staticfiles/"

rm -rf -- "$static_build_dir"
trap - EXIT


exec supervisord -c /etc/supervisord.conf
