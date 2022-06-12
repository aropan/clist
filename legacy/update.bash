#!/usr/bin/env bash

set -x -e

exec 200>/tmp/update.lock
flock -n 200 || { date; echo "Script is already running"; exit 0; }

cd "$(dirname "${BASH_SOURCE[0]}")"

python3 api/google_calendar/common.py

mkdir -p logs/update
mkdir -p logs/working
php -f update.php 2>&1 | tee logs/update/index.html
