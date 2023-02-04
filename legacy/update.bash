#!/usr/bin/env bash

set -x -e

exec 200>/tmp/update.lock
flock -n 200 || { date; echo "Script is already running"; exit 0; }

cd "$(dirname "${BASH_SOURCE[0]}")"

SENTRY_CONF_FILE=/run/secrets/sentry_conf
if [ -f $SENTRY_CONF_FILE ]; then
  export $(cat $SENTRY_CONF_FILE | xargs)
fi

run_command() {
  cmd=$1
  monitor_id=$2
  if [ -n "$monitor_id" ]; then
    sentry-cli monitors run $monitor_id -- $cmd
  else
    $cmd
  fi
}

python3 api/google_calendar/common.py

mkdir -p logs/update
mkdir -p logs/working
run_command "php -f update.php 2>&1" "$SENTRY_CRON_MONITOR_LIST_UPDATE" | tee logs/update/index.html
