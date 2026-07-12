#!/usr/bin/env bash

set -x -e

exec 200>/tmp/update.lock
flock -n 200 || { date; echo "Script is already running"; exit 0; }

cd "$(dirname "${BASH_SOURCE[0]}")"

MONITORING_CONF_FILE=/run/secrets/monitoring_conf
if [ -f $MONITORING_CONF_FILE ]; then
  export $(cat $MONITORING_CONF_FILE | xargs)
fi

run_command() {
  cmd=$1
  monitor_name=$2
  ping_url=
  if [ -n "$monitor_name" ] && [ -n "$HEALTHCHECKS_PING_URL" ] && [ -n "$HEALTHCHECKS_PING_KEY" ]; then
    ping_url=$HEALTHCHECKS_PING_URL/$HEALTHCHECKS_PING_KEY/$monitor_name
    curl -fsS -m 10 --retry 3 -o /dev/null "$ping_url/start?create=1" || true
  fi
  rc=0
  $cmd || rc=$?
  if [ -n "$ping_url" ]; then
    curl -fsS -m 10 --retry 3 -o /dev/null "$ping_url/$rc" || true
  fi
  return $rc
}

python3 api/google_calendar/common.py

run_command "php -f update.php 2>&1" list-update | tee logs/update.log
