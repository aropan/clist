#!/usr/bin/env bash

set -euo pipefail

static_build_dir="$(mktemp -d /tmp/clist-static.XXXXXX)"
trap 'rm -rf -- "$static_build_dir"' EXIT

STATIC_ROOT="$static_build_dir" python manage.py collectstatic --noinput
mkdir -p "$APPDIR/staticfiles"
rsync --archive --delay-updates --delete-delay "$static_build_dir/" "$APPDIR/staticfiles/"

rm -rf -- "$static_build_dir"
trap - EXIT


exec supervisord -c /etc/supervisord.conf
