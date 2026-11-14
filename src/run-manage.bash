#!/usr/bin/env bash

# No `set -x`: the ping key is part of the ping URL, so xtrace would leak it to the log.
set -e

name=$1

if [[ ${CRON_SKIP_CHECKS:-0} == 1 ]]; then
    set -- "$@" --skip-checks
fi

exec 200>/tmp/$name.lock
flock -n 200 || { date; echo "Script '$name' is already running"; exit 0; }

if [[ ${CRON_JITTER_SECONDS:-0} -gt 0 ]]; then
    printf -v jitter_seconds '%d.%03d' "$((RANDOM % CRON_JITTER_SECONDS))" "$((RANDOM % 1000))"
    sleep "$jitter_seconds"
fi

cd "$(dirname "$0")"

# Healthchecks helpers, shared with the legacy runner (see that file).
. ./scripts/healthchecks.bash
hc_load_monitoring_conf

logdir=./logs/manage
logfile=$logdir/$name.log
mkdir -p $logdir
rm -f $logfile
echo -e "BEGIN $(date)\n\n" >>$logfile

rc=0
hc_run "$MONITOR_NAME" "$logfile" ./manage.py "$@" || rc=$?

echo -e "\n\nEND $(date)" >>$logfile
exit $rc
